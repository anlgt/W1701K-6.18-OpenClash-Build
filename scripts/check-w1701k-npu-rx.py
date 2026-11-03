#!/usr/bin/env python3
"""Compile the actual mt76 NPU RX functions against DMA/ring fixtures.

These tests model device completion and visibility, not physical DMA timing.
Run --expect-broken on the pinned unpatched source to reproduce each race.
"""
import os
import re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path


def function(text, name):
    match = re.search(r'(?:static )?(?:int|struct sk_buff \*)\s*' + name + r'\([^;]+?\)\n\{', text)
    if not match:
        raise SystemExit('Cannot locate actual C function: ' + name)
    end, depth = match.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]


source = Path(sys.argv[1])
text = (source / 'npu.c').read_text()
header = (source / 'airoha_offload.h').read_text()
macros = '\n'.join(line for line in header.splitlines() if line.startswith('#define NPU_RX_DMA_'))
descriptor = re.search(r'struct airoha_npu_rx_dma_desc \{.*?\} __packed;', header, re.S)
if not descriptor:
    raise SystemExit('Missing actual NPU RX descriptor declaration')

prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
typedef uint32_t u32; typedef uint64_t u64;
#define __packed __attribute__((packed))
#define BIT(n) (1U << (n))
#define GENMASK(h,l) (((~0U) >> (31-(h))) & ((~0U) << (l)))
#define max_t(type,a,b) ((type)(a) > (type)(b) ? (type)(a) : (type)(b))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define SKB_WITH_OVERHEAD(size) ((size)-32)
#define SLOTS 8
'''
stubs = r'''
struct page { char data[512]; unsigned id; bool freed; };
struct skb_shared_info { int nr_frags; void *frags[16]; };
struct sk_buff { int len; struct page *page; struct skb_shared_info sh; };
struct mt76_queue_entry { void *buf; unsigned dma_len[1], dma_addr[1]; };
struct mt76_queue {
    struct airoha_npu_rx_dma_desc *desc;
    struct mt76_queue_entry *entry;
    int queued, ndesc, head, tail, buf_size;
    void *page_pool;
};
struct mt76_dev { void *dma_dev; };
static struct page pages[64];
static struct sk_buff skbs[64];
static struct airoha_npu_rx_dma_desc descriptors[SLOTS];
static struct mt76_queue_entry entries[SLOTS];
static struct mt76_dev dev;
static struct mt76_queue q;
static int allocated, alloc_limit, built, freed, synced, writes, published;
static int barriers, info_reads, ctrl_reads, hidden_count, hidden_len;
static bool count_race, alloc_skb_failure;

static void complete_frame(int count, int length) {
    for (int i=0; i<count; i++) {
        int index=(q.tail+i)%q.ndesc;
        descriptors[index].ctrl=NPU_RX_DMA_DESC_DONE_MASK | ((length+i)<<1);
        descriptors[index].info=(u32)count<<28;
    }
}
/* A count read may race device completion. Returning the old value while
 * making DONE visible reproduces the original count-before-DONE bug. */
static u32 field_get(u32 mask, u32 value) {
    if (mask==NPU_RX_DMA_PKT_COUNT_MASK) {
        info_reads++;
        if (count_race) { count_race=false; complete_frame(2,70); }
    }
    if (mask==NPU_RX_DMA_DESC_DONE_MASK) ctrl_reads++;
    return (value&mask)>>__builtin_ctz(mask);
}
#define FIELD_GET(mask,value) field_get((mask),(value))
static void dma_rmb(void) {
    barriers++;
    /* Coherent DMA visibility fixture: info/payload metadata become visible
     * after their respective ownership/read barriers. */
    if (barriers==1 && hidden_count) {
        descriptors[q.tail].info=(u32)hidden_count<<28;
    }
    if (barriers==2 && hidden_len) {
        for (int i=0; i<hidden_count; i++)
            descriptors[(q.tail+i)%q.ndesc].ctrl=NPU_RX_DMA_DESC_DONE_MASK | ((hidden_len+i)<<1);
    }
}
static struct page *virt_to_head_page(void *buf) {
    for (int i=0; i<allocated; i++) if (buf==pages[i].data) return &pages[i];
    assert(!"buffer is not backed by an allocated page"); return NULL;
}
static void *page_address(struct page *p) { return p->data; }
static unsigned page_pool_get_dma_addr(struct page *p) { return 0x1000*(p->id+1); }
static int page_pool_get_dma_dir(void *pool) { (void)pool; return 0; }
static void *mt76_get_page_pool_buf(struct mt76_queue *queue, int *offset, int size) {
    (void)queue; assert(size<=512); *offset=0;
    if (allocated==alloc_limit) return NULL;
    assert(allocated<(int)ARRAY_SIZE(pages));
    pages[allocated].id=allocated;
    return pages[allocated++].data;
}
static void mock_write(struct mt76_queue *queue, int value) {
    assert(queue==&q && value>=0 && value<q.ndesc);
    writes++; published=value;
}
#define Q_WRITE(queue,field,value) mock_write((queue),(value))
static void dma_sync_single_for_cpu(void *device, unsigned addr, unsigned len, int dir) {
    (void)device; (void)dir; assert(addr && len); synced++;
    unsigned id=addr/0x1000-1; assert(id<(unsigned)allocated && !pages[id].freed);
}
static struct sk_buff *napi_build_skb(void *buf, int size) {
    (void)size;
    if (alloc_skb_failure) return NULL;
    assert(built<(int)ARRAY_SIZE(skbs));
    struct sk_buff *skb=&skbs[built++]; skb->page=virt_to_head_page(buf);
    assert(!skb->page->freed); return skb;
}
static void __skb_put(struct sk_buff *skb, int len) { skb->len+=len; }
static void skb_reset_mac_header(struct sk_buff *skb) { (void)skb; }
static void skb_mark_for_recycle(struct sk_buff *skb) { (void)skb; }
static struct skb_shared_info *skb_shinfo(struct sk_buff *skb) { return &skb->sh; }
static void skb_add_rx_frag(struct sk_buff *skb, int index, struct page *p, int offset, int len, int size) {
    (void)offset; (void)size; assert(index<16 && !p->freed);
    skb->sh.frags[index]=p; skb->sh.nr_frags=index+1; skb->len+=len;
}
static void dev_kfree_skb(struct sk_buff *skb) {
    if (!skb) return;
    freed++; skb->page->freed=true;
    for (int i=0; i<skb->sh.nr_frags; i++) ((struct page*)skb->sh.frags[i])->freed=true;
}
static void reset(void) {
    memset(pages,0,sizeof(pages)); memset(skbs,0,sizeof(skbs));
    memset(descriptors,0,sizeof(descriptors)); memset(entries,0,sizeof(entries));
    q=(struct mt76_queue){.desc=descriptors,.entry=entries,.ndesc=SLOTS,.buf_size=512};
    allocated=built=freed=synced=writes=barriers=info_reads=ctrl_reads=0;
    hidden_count=hidden_len=0; published=-1; alloc_limit=64;
    count_race=alloc_skb_failure=false;
}
'''
main = r'''
static void prime(void) {
    assert(mt76_npu_fill_rx_queue(&dev,&q)==SLOTS-1);
    assert(q.head==SLOTS-1 && q.tail==0 && q.queued==SLOTS-1);
    writes=0; published=-1;
}
static void assert_untouched(int tail, int queued) {
    assert(q.tail==tail && q.queued==queued && built==0 && freed==0 && synced==0 && writes==0);
}
int main(int argc, char **argv) {
    assert(argc==2); (void)dev_kfree_skb; (void)dma_rmb; reset(); u32 info=0;
    if (!strcmp(argv[1],"publish")) {
        prime(); complete_frame(1,70);
        assert(mt76_npu_dequeue(&dev,&q,&info));
        /* Dequeue must not hand any buffer still owned by the stack to DMA. */
        assert(writes==0 && q.tail==1 && q.queued==6);
        assert(mt76_npu_fill_rx_queue(&dev,&q)==1);
        assert(writes==1 && published==1 && q.head==0 && q.queued==7);
        assert(entries[7].buf==pages[7].data && descriptors[7].addr==0x8000);
    } else if (!strcmp(argv[1],"partial")) {
        prime(); complete_frame(2,70); descriptors[1].ctrl=0;
        assert(!mt76_npu_dequeue(&dev,&q,&info)); assert_untouched(0,7);
        descriptors[1].ctrl=1|(71<<1);
        struct sk_buff *skb=mt76_npu_dequeue(&dev,&q,&info);
        assert(skb && skb->len==141 && q.tail==2 && q.queued==5 && !freed);
    } else if (!strcmp(argv[1],"count_race")) {
        prime(); count_race=true;
        assert(!mt76_npu_dequeue(&dev,&q,&info)); assert_untouched(0,7);
        assert(info_reads==0); count_race=false; complete_frame(2,70);
        struct sk_buff *skb=mt76_npu_dequeue(&dev,&q,&info);
        assert(skb && skb->len==141 && q.tail==2 && q.queued==5);
    } else if (!strcmp(argv[1],"dma_visibility")) {
        prime(); descriptors[0].ctrl=descriptors[1].ctrl=1;
        hidden_count=2; hidden_len=70;
        struct sk_buff *skb=mt76_npu_dequeue(&dev,&q,&info);
        assert(skb && skb->len==141 && q.tail==2 && q.queued==5 && barriers==2);
    } else if (!strcmp(argv[1],"empty")) {
        prime(); complete_frame(1,70); q.queued=0;
        assert(!mt76_npu_dequeue(&dev,&q,&info)); assert_untouched(0,0);
        assert(!info_reads && !ctrl_reads);
    } else if (!strcmp(argv[1],"too_many_slots")) {
        prime(); complete_frame(3,70); q.queued=2;
        assert(!mt76_npu_dequeue(&dev,&q,&info)); assert_untouched(0,2);
    } else if (!strcmp(argv[1],"wrap")) {
        prime(); q.tail=6; complete_frame(1,70);
        assert(mt76_npu_dequeue(&dev,&q,&info));
        /* Use the ring at a wrapped head/tail with 2-slot frame across end. */
        assert(mt76_npu_fill_rx_queue(&dev,&q)==1);
        q.tail=7; q.queued=7; q.head=6; complete_frame(2,70);
        struct sk_buff *skb=mt76_npu_dequeue(&dev,&q,&info);
        assert(skb && skb->len==141 && q.tail==1 && q.queued==5);
    } else if (!strcmp(argv[1],"zero_count")) {
        prime(); complete_frame(1,70); descriptors[0].info=0;
        struct sk_buff *skb=mt76_npu_dequeue(&dev,&q,&info);
        assert(skb && skb->len==70 && q.tail==1 && q.queued==6);
    } else if (!strcmp(argv[1],"no_buffer")) {
        alloc_limit=0;
        assert(mt76_npu_fill_rx_queue(&dev,&q)==0);
        assert(q.head==0 && q.tail==0 && q.queued==0 && writes==1 && published==1);
    } else if (!strcmp(argv[1],"partial_refill")) {
        prime(); complete_frame(3,70);
        assert(mt76_npu_dequeue(&dev,&q,&info));
        writes=0; alloc_limit=8;
        assert(mt76_npu_fill_rx_queue(&dev,&q)==1);
        /* Slot7 alone gets a fresh buffer; old slots0/1 are not published. */
        assert(q.head==0 && q.tail==3 && q.queued==5 && published==1 && writes==1);
        assert(entries[7].buf==pages[7].data && descriptors[7].ctrl==0);
        writes=0;
        assert(mt76_npu_fill_rx_queue(&dev,&q)==0);
        assert(q.head==0 && q.queued==5 && published==1 && writes==1);
    } else if (!strcmp(argv[1],"skb_oom")) {
        prime(); complete_frame(1,70); alloc_skb_failure=true;
        assert(!mt76_npu_dequeue(&dev,&q,&info));
        assert(q.tail==0 && q.queued==7 && !built && !freed && !writes && synced==1);
        alloc_skb_failure=false;
        assert(mt76_npu_dequeue(&dev,&q,&info)); assert(q.tail==1 && q.queued==6);
    } else if (!strcmp(argv[1],"cycles")) {
        prime();
        for (int cycle=0; cycle<16; cycle++) {
            complete_frame(2,70);
            struct sk_buff *skb=mt76_npu_dequeue(&dev,&q,&info);
            assert(skb && skb->len==141 && q.queued==5);
            assert(mt76_npu_fill_rx_queue(&dev,&q)==2);
            assert(q.queued==7 && published==q.tail && q.head==(q.tail+7)%8);
        }
    } else { assert(!"unknown scenario"); }
    return 0;
}
'''
code = prelude + macros + '\n' + descriptor[0] + '\n' + stubs + '\n'
code += '\n'.join(function(text, name) for name in ('mt76_npu_fill_rx_queue', 'mt76_npu_dequeue'))
code += main
scenarios = ('publish', 'partial', 'count_race', 'dma_visibility', 'empty', 'too_many_slots',
             'wrap', 'zero_count', 'no_buffer', 'partial_refill', 'skb_oom', 'cycles')
old_failures = {'publish', 'partial', 'count_race', 'dma_visibility', 'empty', 'too_many_slots',
                'no_buffer', 'partial_refill'}
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'npu-rx.c'
    path.write_text(code)
    binary = path.with_suffix('')
    subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-parameter', '-Wno-sign-compare', str(path), '-o', str(binary)], check=True)
    for scenario in scenarios:
        result = subprocess.run([str(binary), scenario], capture_output=True, text=True)
        if '--expect-broken' in sys.argv[2:] and scenario in old_failures:
            if result.returncode != -signal.SIGABRT:
                raise SystemExit(f'Unpatched NPU RX did not reproduce {scenario}: {result.returncode}')
        elif result.returncode:
            print(result.stderr, file=sys.stderr)
            raise SystemExit(f'NPU RX fixture failed: {scenario}')
print('PASS: ' + ('unpatched NPU RX reproduces eight ownership/completion races'
                 if '--expect-broken' in sys.argv[2:] else
                 'actual NPU RX functions pass 12 ownership, completion, DMA-order, wrap and allocation fixtures'))
