// SPDX-License-Identifier: MIT
//! One bounded, deterministic TCP transfer or UDP echo sequence for lab use.
use std::env;
use std::io::{self, Read, Write};
use std::net::{IpAddr, Shutdown, SocketAddr, TcpListener, UdpSocket};
use std::time::Duration;

const LIMIT: usize = 32 * 1024 * 1024;
const CHUNK: usize = 64 * 1024;
const TIMEOUT: Duration = Duration::from_secs(10);

// Position-based pattern with period far longer than an Ethernet frame.
// The remote host computes it independently, including partial chunks.
fn pattern(pos: usize) -> u8 {
    let mut x = (pos as u64).wrapping_add(0x9e37_79b9_7f4a_7c15);
    x = (x ^ (x >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    x = (x ^ (x >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    (x ^ (x >> 31)) as u8
}

fn tcp(bind: SocketAddr, peer: IpAddr, send: bool, len: usize) -> io::Result<()> {
    if len == 0 || len > LIMIT {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "invalid length",
        ));
    }
    let listener = TcpListener::bind(bind)?;
    println!("READY");
    io::stdout().flush()?;
    let (mut stream, addr) = listener.accept()?;
    if addr.ip() != peer {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "unexpected peer",
        ));
    }
    stream.set_read_timeout(Some(TIMEOUT))?;
    stream.set_write_timeout(Some(TIMEOUT))?;
    let mut buffer = vec![0; CHUNK];
    let mut offset = 0;
    while offset < len {
        let count = (len - offset).min(buffer.len());
        let bytes = &mut buffer[..count];
        if send {
            for (i, b) in bytes.iter_mut().enumerate() {
                *b = pattern(offset + i);
            }
            stream.write_all(bytes)?;
        } else {
            stream.read_exact(bytes)?;
            if let Some(i) = bytes
                .iter()
                .enumerate()
                .position(|(i, &b)| b != pattern(offset + i))
            {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    format!("payload mismatch at {}", offset + i),
                ));
            }
        }
        offset += count;
    }
    if send {
        stream.shutdown(Shutdown::Write)?;
        let mut ack = [0; 8];
        stream.read_exact(&mut ack)?;
        if u64::from_be_bytes(ack) != len as u64 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "bad peer acknowledgement",
            ));
        }
    } else {
        let mut extra = [0; 1];
        if stream.read(&mut extra)? != 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "unexpected extra payload",
            ));
        }
        stream.write_all(&(len as u64).to_be_bytes())?;
        stream.shutdown(Shutdown::Write)?;
    }
    println!("PASS bytes={len}");
    Ok(())
}

fn udp(bind: SocketAddr, peer: IpAddr, count: usize) -> io::Result<()> {
    if count == 0 || count > 4096 {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "invalid count"));
    }
    let socket = UdpSocket::bind(bind)?;
    socket.set_read_timeout(Some(TIMEOUT))?;
    socket.set_write_timeout(Some(TIMEOUT))?;
    println!("READY");
    io::stdout().flush()?;
    let mut buffer = [0; 2048];
    let mut bytes = 0usize;
    for seq in 0..count {
        let (len, addr) = socket.recv_from(&mut buffer)?;
        if addr.ip() != peer || len < 8 || buffer[..8] != (seq as u64).to_be_bytes() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "UDP peer or sequence mismatch",
            ));
        }
        if buffer[8..len]
            .iter()
            .enumerate()
            .any(|(i, &b)| b != pattern(seq * 2048 + i))
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidData,
                "UDP payload mismatch",
            ));
        }
        if socket.send_to(&buffer[..len], addr)? != len {
            return Err(io::Error::new(io::ErrorKind::WriteZero, "short UDP send"));
        }
        bytes += len;
    }
    println!("PASS datagrams={count} bytes={bytes}");
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = env::args().collect();
    if args.len() != 5 {
        return Err("usage: payload-peer tcp-send|tcp-receive|udp BIND PEER COUNT".into());
    }
    let bind = args[2].parse()?;
    let peer = args[3].parse()?;
    let count = args[4].parse()?;
    match args[1].as_str() {
        "tcp-send" => tcp(bind, peer, true, count)?,
        "tcp-receive" => tcp(bind, peer, false, count)?,
        "udp" => udp(bind, peer, count)?,
        _ => return Err("invalid mode".into()),
    }
    Ok(())
}
