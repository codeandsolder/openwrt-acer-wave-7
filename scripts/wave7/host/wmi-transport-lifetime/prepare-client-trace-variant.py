#!/usr/bin/env python3
"""Derive a guarded trace variant from a known-working helper directory."""
import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

MODULES = {
    "mt76": "mt76.ko",
    "mt76_connac_lib": "mt76-connac-lib.ko",
    "mt792x_lib": "mt792x-lib.ko",
    "mt7925_common": "mt7925-common.ko",
    "mt7925e": "mt7925e.ko",
}


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"expected exactly one {old!r}")
    return text.replace(old, new)


def extend_crash_profile(text, old, new):
    """Inherit every existing event/probe condition, including nested ones."""
    pattern = re.compile(
        rf"(?m)^([ \t]*)(if \[\[ )?(\$variant == {re.escape(old)})( \|\|| \]\]; then)$"
    )

    def expand(match):
        indent, prefix, condition, suffix = match.groups()
        prefix = prefix or ""
        return (indent + prefix + condition + " ||\n"
                + indent + " " * len(prefix) + "$variant == " + new + suffix)

    extended, count = pattern.subn(expand, text)
    if count < 2 or count != text.count(old):
        raise ValueError(f"unsupported crash profile references for {old}: {count}/{text.count(old)}")
    return extended


def selftest():
    old, new = "old-trace", "new-trace"
    fixture = (
        "if [[ $variant == old-trace ||\n"
        "      $variant == other ]]; then\n"
        "    if [[ $variant == old-trace ]]; then\n"
        "        :\n"
        "    fi\n"
        "fi\n"
        "if [[ $variant == other ||\n"
        "      $variant == old-trace ]]; then\n"
        "    :\n"
        "fi\n"
    )
    result = extend_crash_profile(fixture, old, new)
    assert result.count(old) == result.count(new) == 3
    assert "if [[ $variant == old-trace ||\n          $variant == new-trace ]]; then" in result
    subprocess.run(["bash", "-n"], input=result, text=True, check=True)
    try:
        extend_crash_profile(fixture + "echo old-trace\n", old, new)
    except ValueError:
        pass
    else:
        raise AssertionError("unhandled variant reference accepted")
    print("TRACE_VARIANT_SELFTEST_PASS")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("previous", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("bundle", type=Path)
    p.add_argument("old")
    p.add_argument("new")
    args = p.parse_args()
    for variant in (args.old, args.new):
        if not re.fullmatch(r"upstream-prefix22-authorize-delayed-links-[a-z0-9-]+-trace", variant):
            p.error(f"invalid trace variant: {variant}")
    if args.old == args.new:
        p.error("new variant must differ")
    old, new = args.old, args.new
    names = ("client-module-stack.sh", "client-crash-stream.sh", "client-trace-window.sh")
    source = {name: (args.previous / name).read_text() for name in names}
    if any(new in content for content in source.values()):
        p.error("new variant already exists")
    s = source[names[0]]
    start = s.index(f"\n{old})\n") + 1
    end = s.index("\n;;", start) + 3
    block = s[start:end].replace(old, new, 1)
    pins = {kind: {} for kind in ("hash", "version", "id")}
    for module, filename in MODULES.items():
        path = args.bundle / filename
        if command("modinfo", "-F", "name", str(path)) != module:
            raise ValueError(f"wrong module identity: {path}")
        pins["hash"][module] = hashlib.sha256(path.read_bytes()).hexdigest()
        pins["version"][module] = command("modinfo", "-F", "srcversion", str(path))
        build_id = re.findall(r"Build ID: ([0-9a-f]+)", command("readelf", "-n", str(path)))
        if len(build_id) != 1:
            raise ValueError(f"ambiguous build ID: {path}")
        pins["id"][module] = build_id[0]
    for kind, values in pins.items():
        header = f"declare -A candidate_{kind}=(\n"
        start_pin = block.index(header) + len(header)
        end_pin = block.index("\n)", start_pin)
        body = block[start_pin:end_pin]
        for module, value in values.items():
            pattern = rf"(?m)^    \[{module}\]=[0-9A-Fa-f]+$"
            body, count = re.subn(pattern, f"    [{module}]={value}", body)
            if count != 1:
                raise ValueError(f"missing or duplicate {kind} pin for {module}")
        block = block[:start_pin] + body + block[end_pin:]
    s = s[:end] + "\n" + block + s[end:]
    line = f"    [{old}]=association-rxtx"
    source[names[0]] = replace_once(s, line, line + f"\n    [{new}]=association-rxtx")
    source[names[1]] = extend_crash_profile(source[names[1]], old, new)
    source[names[2]] = replace_once(source[names[2]], f"--{old})", f"--{old}|--{new})")
    args.output.mkdir(parents=True, exist_ok=False)
    for name, content in source.items():
        target = args.output / name
        target.write_text(content)
        target.chmod((args.previous / name).stat().st_mode & 0o777)
        subprocess.run(["bash", "-n", str(target)], check=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        selftest()
    else:
        main()
