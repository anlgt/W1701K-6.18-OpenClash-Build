#!/usr/bin/env python3
"""Execute actual prepared CPU PLL and PHY temperature functions with I/O stubs."""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(sys.argv[1])
cpu = (root / 'drivers/pmdomain/mediatek/airoha-cpu-pmdomain.c').read_text()
phy = (root / 'drivers/net/phy/air_en8811h.c').read_text()

def function(source, name):
    match = re.search(r'static\s+(?:unsigned long|int|bool|void)\s+' + name + r'\([^;]+?\)\n\{', source)
    if not match:
        raise SystemExit('Missing actual kernel function: ' + name)
    end, depth = match.end(), 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[match.start():end]

prelude = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <errno.h>
#include <limits.h>
typedef uint32_t u32; typedef int32_t s32;
#define __iomem
#define BIT(n) (1U << (n))
#define GENMASK(h,l) (((~0U) >> (31-(h))) & ((~0U) << (l)))
#define FIELD_GET(mask,val) (((val) & (mask)) >> __builtin_ctz(mask))
#define FIELD_PREP(mask,val) (((val) << __builtin_ctz(mask)) & (mask))
#define container_of(ptr,type,member) ((type*)((char*)(ptr)-offsetof(type,member)))
struct clk_hw { void *init; }; struct generic_pm_domain { int unused; };
struct arm_smccc_res { unsigned long a0; };
static unsigned long smc_result;
#define arm_smccc_1_1_invoke(a,b,c,d,e,f,g,h,out) ((out)->a0=smc_result)
static unsigned int writes, irq_depth, switches;
static u32 scu[256], mcu[512];
static u32 readl(void *p) { return *(u32*)p; }
static void writel(u32 value, void *p) {
    writes++;
    if (p == &mcu[0x7c0/4]) {
        assert(((value>>9)&3) == (switches%2 ? 1 : 3)); switches++;
    }
    *(u32*)p = value;
}
#define local_irq_save(flags) ((flags)=0,irq_depth++)
#define local_irq_restore(flags) ((void)(flags),assert(irq_depth==1),irq_depth--)
static void udelay(unsigned int us) { assert(us==20 && irq_depth==1); }
'''
defines = cpu[cpu.index('#define AIROHA_SIP'):cpu.index('struct airoha_cpu_pmdomain_priv')]
struct = re.search(r'struct airoha_cpu_pmdomain_priv \{.*?\n\};', cpu, re.S).group()
functions = '\n'.join(function(cpu, n) for n in (
    'airoha_cpu_smc_clk_get', 'airoha_cpu_pll_clk_get', 'airoha_cpu_pmdomain_clk_get',
    'airoha_cpu_smc_set_freq', 'airoha_cpu_clock_switch', 'airoha_cpu_pll_set_freq',
    'airoha_cpu_pmdomain_set_performance_state', 'airoha_cpu_smc_available'))
phy_stubs = r'''
enum hwmon_sensor_types { hwmon_temp, hwmon_other };
#define hwmon_temp_input 1
#define MDIO_MMD_VEND1 30
#define EN8811H_PHY_FW_STATUS 0x8009
#define EN8811H_PHY_READY 2
struct phy_device { int lock; };
struct device { void *data; };
static void *dev_get_drvdata(struct device *d) { return d->data; }
static int mmd_status, command_error, read_error, command_count;
static u32 temperature;
static void mutex_lock(int *lock) { assert(!*lock); *lock=1; }
static void mutex_unlock(int *lock) { assert(*lock); *lock=0; }
static int phy_read_mmd(struct phy_device *p, int mmd, int reg) {
    assert(p->lock && mmd==30 && reg==0x8009); return mmd_status;
}
static int phy_write_mmd(struct phy_device *p, int mmd, int reg, int val) {
    assert(p->lock && mmd==30);
    command_count++;
    assert(reg==(command_count==1?0x800e:0x800f));
    assert(val==(command_count==1?0x1100:0xe5));
    return command_count==command_error ? -EIO : 0;
}
static int air_buckpbus_reg_read(struct phy_device *p, u32 reg, u32 *raw) {
    assert(p->lock && reg==0x3b38 && command_count==2); *raw=temperature; return read_error;
}
'''
main = r'''
int main(void) {
    struct airoha_cpu_pmdomain_priv p={.pll_base=scu,.mcucfg=mcu};
    smc_result=1200; assert(airoha_cpu_smc_available());
    p.use_smc=true; assert(airoha_cpu_pmdomain_clk_get(&p.hw,0)==1200000000UL);
    assert(airoha_cpu_pmdomain_set_performance_state(&p.pd,14)==0 && !writes);
    smc_result=0; assert(!airoha_cpu_smc_available());
    smc_result=ULONG_MAX; assert(!airoha_cpu_smc_available());
    p.use_smc=false;
    /* An inherited 1400 MHz PLL must be measured honestly, not clamped. */
    scu[0x2b4/4]=28U<<24; scu[0x2b8/4]=0;
    assert(airoha_cpu_pll_clk_get(&p)==1400000000UL && !writes);
    assert(airoha_cpu_pmdomain_clk_get(&p.hw,0)==1400000000UL && !writes);
    for (unsigned int i=0;i<=14;i++) {
        scu[0x2b4/4]=0x123456; switches=0;
        assert(airoha_cpu_pmdomain_set_performance_state(&p.pd,i)==0);
        assert(airoha_cpu_pll_clk_get(&p)==(500UL+i*50)*1000000);
        assert((scu[0x2b4/4]&0xffffff)==0x123456);
        assert((scu[0x1e0/4]&5)==1 && !irq_depth && switches==2);
    }
    unsigned int old_writes=writes;
    assert(airoha_cpu_pll_set_freq(&p,15)==-EINVAL);
    assert(airoha_cpu_pll_set_freq(&p,UINT_MAX)==-EINVAL && writes==old_writes);
    struct phy_device pd={0}; struct device dev={.data=&pd}; long output;
    mmd_status=2;
    int samples[]={-40,-5,0,47,150};
    for (unsigned int i=0;i<sizeof(samples)/sizeof(samples[0]);i++) {
        temperature=samples[i]; command_count=0; output=123;
        assert(en8811h_hwmon_read(&dev,hwmon_temp,1,0,&output)==0);
        assert(output==samples[i]*1000L && !pd.lock && command_count==2);
    }
    command_count=0; assert(en8811h_hwmon_read(&dev,hwmon_other,1,0,&output)==-EOPNOTSUPP && !command_count);
    mmd_status=-EIO; output=123; assert(en8811h_hwmon_read(&dev,hwmon_temp,1,0,&output)==-EIO && output==123 && !pd.lock);
    mmd_status=0; assert(en8811h_hwmon_read(&dev,hwmon_temp,1,0,&output)==-EAGAIN && !pd.lock);
    mmd_status=2;
    for (int i=1;i<=2;i++) {
        command_count=0; command_error=i;
        assert(en8811h_hwmon_read(&dev,hwmon_temp,1,0,&output)==-EIO && !pd.lock && output==123);
    }
    command_error=0; command_count=0; read_error=-EIO;
    assert(en8811h_hwmon_read(&dev,hwmon_temp,1,0,&output)==-EIO && !pd.lock && output==123);
    read_error=0; command_count=0; temperature=151;
    assert(en8811h_hwmon_read(&dev,hwmon_temp,1,0,&output)==-ENODATA && !pd.lock && output==123);
    puts("PASS: actual PLL code covers all stock OPPs, divider/bit preservation and write-free bounds rejection; PHY code covers units, valid zero, errors and MCU locking");
}
'''
code = prelude + defines + struct + functions + phy_stubs + function(phy, 'en8811h_hwmon_read') + main
with tempfile.TemporaryDirectory() as directory:
    source=Path(directory)/'status.c';source.write_text(code);binary=source.with_suffix('')
    subprocess.run([os.environ.get('CC','cc'),'-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-parameter',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
