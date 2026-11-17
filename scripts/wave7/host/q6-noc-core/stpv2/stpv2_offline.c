/* Standalone validation harness for unchanged Zephyr STPv2 decoder.
 * Licensed independently from the Zephyr decoder. Archives only counts
 * and bounded samples; does not infer Qualcomm-specific transaction fields.
 */
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <zephyr/debug/mipi_stp_decoder.h>
static uint64_t events[256];
static uint64_t by_major[256];
static uint16_t current_major;
static uint16_t current_channel;
static size_t shown;
static size_t sequence;
static FILE *event_file;
static bool cb(enum mipi_stp_decoder_ctrl_type type, union mipi_stp_decoder_data data,
               uint64_t *ts, bool marked) {
    if ((unsigned)type < 256) events[type]++;
    if (type == STP_DECODER_MAJOR) current_major = data.id;
    if (type == STP_DECODER_CHANNEL) current_channel = data.id;
    if (type == STP_DATA4 || type == STP_DATA8 || type == STP_DATA16 ||
        type == STP_DATA32 || type == STP_DATA64) by_major[current_major & 0xff]++;
    if (event_file) {
        fprintf(event_file, "%zu,%d,%u,%u,%d,%" PRIu64 ",0x%016" PRIx64 "\n",
                sequence, type, current_major, current_channel, (int)marked,
                ts ? *ts : 0, data.data);
    }
    sequence++;
    if (shown < 50 &&
        (type == STP_DECODER_ASYNC || type == STP_DECODER_VERSION ||
         type == STP_DECODER_MAJOR || type == STP_DECODER_CHANNEL ||
         type == STP_DATA64 || type == STP_DATA32 || type == STP_DECODER_FREQ)) {
        fprintf(stderr, "EVENT type=%d major=%u channel=%u data=0x%016" PRIx64
                " marked=%d ts=%" PRIu64 "\n", type, current_major,current_channel,
                data.data,(int)marked,ts ? *ts : 0);
        shown++;
    }
    return true;
}
int main(int argc, char **argv) {
    if(argc != 2) {
        fprintf(stderr,"usage: %s source-id39.bin\n",argv[0]);return 2;
    }
    FILE *f=fopen(argv[1],"rb");
    if (!f) {perror("open");return 1;}
    if (fseek(f,0,SEEK_END) != 0) return 3;
    long n=ftell(f);
    if(n<=0 || n>64*1024*1024) return 3;
    rewind(f);
    uint8_t *bytes=malloc((size_t)n);
    if (!bytes) return 3;
    if (fread(bytes,1,(size_t)n,f)!=(size_t)n) return 3;
    fclose(f);
    const char *event_path = getenv("STPV2_EVENTS_TSV");
    if (event_path) {
        event_file = fopen(event_path, "w");
        if (!event_file) { perror("open events"); return 3; }
        fputs("seq,type,major,channel,marked,timestamp,data\n", event_file);
    }
    struct mipi_stp_decoder_config cfg={.start_out_of_sync=true,.cb=cb};
    mipi_stp_decoder_init(&cfg);
    if (mipi_stp_decoder_decode(bytes,(size_t)n)) return 4;
    free(bytes);
    if (event_file) {
        if (fclose(event_file)) return 4;
        event_file = NULL;
    }
    for (int i=0;i<256;i++) if(events[i]) printf("COUNT type=%d n=%" PRIu64 "\n",i,events[i]);
    for (int i=0;i<256;i++) if(by_major[i]) printf("MAJOR %d data_packets=%" PRIu64 "\n",i,by_major[i]);
    return 0;
}
