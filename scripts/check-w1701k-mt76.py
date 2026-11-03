#!/usr/bin/env python3
"""Execute pinned mt76 FEM detection and EEPROM validation with hardware fixtures.

Only MCU/register I/O is stubbed. Compile the real C functions so this catches
an unapplied patch and reproduces the old factory-EEPROM rejection.
"""
import os
import signal
import re
import subprocess
import sys
import tempfile
from pathlib import Path

source = Path(sys.argv[1]) / 'mt7996'

def function(text, name):
    match = re.search(r'static\s+(?:int|bool|void)\s+' + name + r'\([^;]+?\)\n\{', text)
    if not match:
        raise SystemExit('Cannot locate C function: ' + name)
    end, depth = match.end(), 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[match.start():end]

init = (source / 'init.c').read_text()
eeprom = (source / 'eeprom.c').read_text()
macros = '\n'.join(line for line in (source / 'eeprom.h').read_text().splitlines()
                   if line.startswith('#define MT_EE_WIFI_'))
prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
#define BIT(n) (1U << (n))
#define GENMASK(h,l) (((~0U) >> (31-(h))) & ((~0U) << (l)))
#define FIELD_GET(mask,val) (((val) & (mask)) >> __builtin_ctz(mask))
#define u32_get_bits(val,mask) FIELD_GET(mask,val)
#define u8_get_bits(val,mask) FIELD_GET(mask,val)
#define MT_PAD_GPIO 0x700056f0
#define MT_PAD_GPIO_ADIE_SINGLE BIT(15)
#define MT_PAD_GPIO_ADIE_COMB_7992 GENMASK(17,16)
#define MT_PAD_GPIO_ADIE_COMB GENMASK(16,15)
#define MT_ADIE_CHIP_ID(idx) (0x0f00002cU + ((idx) << 28))
#define MT_ADIE_CHIP_ID_MASK GENMASK(31,16)
#define MT_ADIE_VERSION_MASK GENMASK(15,0)
#define MT7996_EEPROM_BLOCK_SIZE 16
#define MT_EE_WIFI_CONF 0x190
#define EEPROM_MODE_EFUSE 2
#define dev_info(...) ((void)0)
enum { MT_BAND0, MT_BAND1, MT_BAND2, __MT_MAX_BAND };
enum { MT7996_FEM_EXT, MT7996_FEM_INT, MT7996_FEM_MIX };
struct mt76_dev { int chip; void *dev; void *phys[3]; struct { u8 *data; } eeprom; };
struct mt7996_dev { struct mt76_dev mt76; struct { u8 fem; } var; };
static bool board;
static u32 pad, ids[3];
static int read_index, rf_error, efuse_error;
static bool is_mt7996(struct mt76_dev *d) { return d->chip == 0x7990; }
static bool is_mt7992(struct mt76_dev *d) { return d->chip == 0x7992; }
static bool of_machine_is_compatible(const char *name) { return board && !strcmp(name, "gemtek,w1701k"); }
static u32 mt76_rr(struct mt7996_dev *d, u32 reg) { (void)d; assert(reg == MT_PAD_GPIO); return pad; }
static int mt7996_mcu_rf_regval(struct mt7996_dev *d, u32 addr, u32 *val, bool set) {
    (void)d; assert(!set); read_index = addr >> 28; assert(read_index < 3);
    *val = ids[read_index]; return rf_error;
}
static int mt7996_mcu_get_eeprom(struct mt7996_dev *d, u32 off, u8 *buf, u32 len, int mode) {
    (void)d; assert(off == 0x470 && mode == EEPROM_MODE_EFUSE);
    memset(buf, 0, len); return efuse_error;
}
'''
main = r'''
int main(void) {
    (void)is_mt7996; (void)of_machine_is_compatible;
    u8 factory[7680] = {0}, def[7680] = {0};
    const u8 conf[] = {0x11,0x23,0x24,0x24,0x25,0x24,0x08,0x0b};
    memcpy(factory+0x190, conf, sizeof(conf)); memcpy(def, factory, sizeof(def));
    struct mt7996_dev d = {.mt76 = {.chip=0x7990, .eeprom={.data=factory}, .phys={(void*)1,(void*)1,(void*)1}}};
    board=true; pad=0x8400; ids[0]=0x79758a02; ids[1]=ids[2]=0x79778a10;
    assert(mt7996_variant_fem_init(&d)==0);
    assert(read_index==1 && d.var.fem==MT7996_FEM_MIX);
    assert(mt7996_eeprom_variant_valid(&d,def));
    factory[0x197]=0xa0; assert(!mt7996_eeprom_variant_valid(&d,def)); factory[0x197]=0x0b;
    factory[0x192]=0x2d; assert(!mt7996_eeprom_variant_valid(&d,def)); factory[0x192]=0x24;
    board=false; assert(mt7996_variant_fem_init(&d)==0 && read_index==0 && d.var.fem==MT7996_FEM_INT);
    factory[0x197]=0xa0; def[0x197]=0xa0; assert(mt7996_eeprom_variant_valid(&d,def));
    board=true; d.mt76.chip=0x7992; pad=BIT(15); assert(mt7996_variant_fem_init(&d)==0 && read_index==0);
    pad=BIT(16); assert(mt7996_variant_fem_init(&d)==0 && read_index==1 && d.var.fem==MT7996_FEM_MIX);
    d.mt76.chip=0x7993; pad=0x8400; assert(mt7996_variant_fem_init(&d)==0 && read_index==0);
    d.mt76.chip=0x7990; rf_error=-EIO; assert(mt7996_variant_fem_init(&d)==-EIO); rf_error=0;
    efuse_error=-EIO; assert(mt7996_variant_fem_init(&d)==-EIO);
    efuse_error=-EINVAL; assert(mt7996_variant_fem_init(&d)==0 && d.var.fem==MT7996_FEM_MIX);
    puts("PASS: W1701K factory mixed FEM accepted; wrong FEM/streams rejected; other chips/boards and error handling preserved");
}
'''
code = prelude + macros + '\n' + '\n'.join([
    function(init, 'mt7996_variant_fem_init'),
    function(eeprom, 'mt7996_eeprom_parse_stream'),
    function(eeprom, 'mt7996_eeprom_variant_valid'),
]) + main
with tempfile.TemporaryDirectory() as directory:
    test = Path(directory) / 'fem.c'
    test.write_text(code)
    binary = test.with_suffix('')
    subprocess.run([os.environ.get('CC', 'cc'), '-std=gnu11', '-Wall', '-Wextra', '-Werror', str(test), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    if '--expect-broken' in sys.argv[2:]:
        if result.returncode != -signal.SIGABRT:
            raise SystemExit('Unpatched driver did not reproduce the FEM assertion failure')
        print('PASS: unpatched driver reproduces W1701K mixed-FEM detection failure')
    else:
        print(result.stdout, end='')
        if result.returncode:
            print(result.stderr, file=sys.stderr)
        result.check_returncode()
