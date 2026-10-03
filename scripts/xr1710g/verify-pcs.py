#!/usr/bin/env python3
"""Focused XR1710G PCS regression gates, using extracted actual driver C.

Usage: python3 verify-pcs.py /path/to/prepared/linux
       python3 verify-pcs.py /path/to/drivers/net/pcs/airoha

Compiles a userspace mock harness around the exact source calibration gate and
an7581_pcs_jcpll_recal() function. This is not a kernel compile or hardware test.
Temporary C/binary outputs are removed automatically. Source files are read-only.
"""
from pathlib import Path
import argparse
import hashlib
import re
import subprocess
import tempfile
import sys


def mask_c(s):
    # Keep offsets, hiding braces in comments/string literals from block matching.
    return re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'',
                  lambda m: ''.join('\n' if c == '\n' else ' ' for c in m[0]),
                  s, flags=re.S)


def block(text, start):
    masked = mask_c(text)
    opening = masked.index('{', start)
    depth = 0
    for end in range(opening, len(masked)):
        if masked[end] == '{':
            depth += 1
        elif masked[end] == '}':
            depth -= 1
            if not depth:
                return text[start:end + 1]
    raise ValueError('unclosed C block')


def function(text, name):
    m = re.search(r'(?m)^(?:static\s+)?(?:int|void)\s+' + re.escape(name) + r'\s*\(', text)
    if not m:
        raise ValueError('missing function ' + name)
    return block(text, m.start())


def normalized_hash(text):
    return hashlib.sha256(re.sub(r'\s+', '', text).encode()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('source_root', type=Path)
    p.add_argument('--cc', default='cc')
    args = p.parse_args()
    pcs = args.source_root
    if not (pcs / 'pcs-airoha-common.c').is_file():
        pcs = pcs / 'drivers/net/pcs/airoha'
    common = (pcs / 'pcs-airoha-common.c').read_text()
    analog = (pcs / 'pcs-an7581.c').read_text()
    header = (pcs / 'pcs-airoha.h').read_text()
    failures = []

    def check(name, passed):
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)
        if not passed:
            failures.append(name)

    probe = function(common, 'airoha_pcs_probe')
    start = re.search(r'if\s*\(device_is_compatible\(dev,\s*"airoha,an7581-pcs-eth"\)', probe)
    if not start:
        raise ValueError('cannot locate actual calibration gate in airoha_pcs_probe')
    gate = block(probe, start.start())
    recal = function(analog, 'an7581_pcs_jcpll_recal')
    initial_write = re.search(r'regmap_field_write\(pcs_ana_fields\[AN7581_PCS_JCPLL_VCO_TCLVAR\],\s*priv->data->port_type.*?\);', analog, re.S)
    if not initial_write:
        raise ValueError('missing initial TCLVAR write')
    definitions = []
    for name in ('AIROHA_SCU_PDIDR', 'AIROHA_SCU_PRODUCT_ID'):
        m = re.search(r'(?m)^#define\s+' + name + r'\s+[^\n]+$', header)
        if not m:
            raise ValueError('missing actual register definition ' + name)
        definitions.append(m[0])

    check('AN7581 TXPCS link-up reset callback absent',
          'an7581_pcs_phya_link_up' not in common + analog + header)
    port = block(header, header.index('struct airoha_pcs_port {'))
    priv = block(header, header.index('struct airoha_pcs_priv {'))
    restart = function(common, 'airoha_pcs_an_restart')
    config = function(common, 'airoha_pcs_config')
    get_state = function(common, 'airoha_pcs_get_state_usxgmii')
    check('per-port interface field and configuration/restart retained',
          'phy_interface_t interface;' in port and
          'phy_interface_t interface;' not in priv and
          'port->interface = interface;' in config and
          'switch (port->interface)' in restart)
    check('new interface-aware RX-lock callback retained',
          'data->rxlock_workaround(priv, index, state->interface)' in get_state and
          re.search(r'an7581_pcs_rxlock_workaround\([^)]*phy_interface_t interface', analog) is not None)
    fir_parse = function(analog, 'an7581_pcs_parse_tx_fir')
    tx_bringup = function(analog, 'an7581_pcs_tx_bringup')
    # These are hashes of the exact original ba2d9bc4 target-patched functions,
    # normalized only for whitespace. They prove 629's parser and application
    # code were retained, instead of checking a hand-rewritten imitation.
    check('629 TX-FIR optional parser retained verbatim (whitespace-insensitive)',
          normalized_hash(fir_parse) == '8e3c377ccc668b29e629f28db07eb1980c83e8ce9d10944ac7912ecc5d99d5a4')
    check('629 TX-FIR application retained verbatim (whitespace-insensitive)',
          normalized_hash(tx_bringup) == 'fbe893ce8341764a8eb7798283fc7d62542c4490457739d32586054e1c10e3c0')
    check('629 TX-FIR parser remains called during field allocation',
          'an7581_pcs_parse_tx_fir(priv)' in function(analog, 'an7581_pcs_alloc_regmap_fields'))
    check('PON RX-lock recovery callback enabled',
          '.rxlock_workaround = an7581_pcs_rxlock_workaround' in
          block(common, common.index('static const struct airoha_pcs_match_data an7581_pcs_pon =')))

    prefix = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
typedef uint32_t u32;
typedef int phy_interface_t;
#define GENMASK(h,l) ((UINT32_MAX >> (31-(h))) & (UINT32_MAX << (l)))
#define FIELD_GET(mask,v) (((v)&(mask))/((mask)&(0u-(mask))))
enum { PHY_INTERFACE_MODE_USXGMII=1, PHY_INTERFACE_MODE_10GBASER,
       PHY_INTERFACE_MODE_SGMII, PHY_INTERFACE_MODE_2500BASEX };
enum { AN7581_PCS_JCPLL_VCO_TCLVAR };
struct device { const char *compatible; };
struct regmap { u32 val; int ret; };
struct regmap_field { int unused; };
enum { AIROHA_PCS_ETH=1, AIROHA_PCS_PON=2 };
struct match_data { int port_type; };
struct airoha_pcs_priv {
    struct regmap *scu;
    bool manual_rx_calib;
    struct regmap_field ***pcs_ana_fields;
    const struct match_data *data;
};
static const char *machine;
static unsigned int writes[8], nwrite, nsleep;
static int test_errors;
static bool device_is_compatible(struct device *dev, const char *s) {
    return strcmp(dev->compatible, s) == 0;
}
static int regmap_read(struct regmap *map, u32 address, u32 *val) {
    (void)address;
    if (map->ret) return map->ret;
    *val = map->val;
    return 0;
}
static bool of_machine_is_compatible(const char *s) {
    return strcmp(machine, s) == 0;
}
static int regmap_field_write(struct regmap_field *field, unsigned int val) {
    (void)field;
    if (nwrite >= 8) abort();
    writes[nwrite++] = val;
    return 0;
}
static void usleep_range(unsigned int low, unsigned int high) {
    if (low != 1000 || high != 2000) abort();
    nsleep++;
}
'''
    # The following strings are actual source extracted above, not recreated
    # conditions. Mocked types and hardware helpers are the only substitutions.
    source = prefix + '\n'.join(definitions)
    source += '\nstatic int exercise_gate(struct device *dev, struct airoha_pcs_priv *priv) {\nint ret;\n'
    source += gate + '\nreturn 0;\n}\n'
    source += recal + '\n'
    source += '\nstatic void exercise_initial(struct airoha_pcs_priv *priv) {\nstruct regmap_field **pcs_ana_fields=priv->pcs_ana_fields[0];\n'
    source += initial_write[0] + '\n}\n'
    source += r'''
static void expect(const char *label, bool ok) {
    printf("%s %s\n", ok ? "PASS" : "FAIL", label);
    if (!ok) test_errors++;
}
int main(void) {
    const char *compat[] = { "airoha,an7581-pcs-eth", "airoha,an7581-pcs-pon",
                            "airoha,an7581-pcs-pcie" };
    const char *boards[] = { "gemtek,xr1710g-ubi", "generic,test-board", "gemtek,w1700k-ubi" };
    struct regmap_field field = {0};
    struct regmap_field *field_row[] = { &field };
    struct regmap_field **field_rows[] = {field_row};
    char label[180];
    unsigned int c, revision, b, mode;
    for (c=0;c<3;c++) {
        for (revision=1;revision<=3;revision++) {
            struct device dev = { compat[c] };
            /* High bits ensure the actual FIELD_GET mask is exercised. */
            struct regmap map = { 0xa5a50000u | revision, 0 };
            struct airoha_pcs_priv priv = { &map, false, field_rows, NULL };
            int ret = exercise_gate(&dev, &priv);
            bool wanted = (c < 2 && revision <= 2);
            snprintf(label,sizeof(label),"actual C gate: %s E%u manual=%u",compat[c],revision,wanted);
            expect(label, ret == 0 && priv.manual_rx_calib == wanted);
        }
    }
    {
        struct device dev = { compat[0] };
        struct regmap map = {2, -5};
        struct airoha_pcs_priv priv = {&map,false,field_rows,NULL};
        expect("actual C gate: SCU read error propagates", exercise_gate(&dev,&priv) == -5);
    }
    for (b=0;b<3;b++) {
        for (mode=1;mode<=4;mode++) {
            struct regmap map = {2,0};
            struct airoha_pcs_priv priv = {&map,false,field_rows,NULL};
            bool wanted = b==2 && (mode==PHY_INTERFACE_MODE_USXGMII || mode==PHY_INTERFACE_MODE_10GBASER);
            machine=boards[b]; nwrite=0; nsleep=0;
            memset(writes,0,sizeof(writes));
            an7581_pcs_jcpll_recal(&priv,0,mode);
            snprintf(label,sizeof(label),"actual C recal: %s interface=%u",boards[b],mode);
            expect(label, wanted ? (nwrite==2 && writes[0]==3 && writes[1]==5 && nsleep==1)
                                 : (nwrite==0 && nsleep==0));
        }
    }
    for (b=0;b<3;b++) {
        for (c=AIROHA_PCS_ETH;c<=AIROHA_PCS_PON;c++) {
            struct regmap map={2,0};
            struct match_data data={c};
            struct airoha_pcs_priv priv={&map,false,field_rows,&data};
            machine=boards[b]; nwrite=0;
            exercise_initial(&priv);
            snprintf(label,sizeof(label),"actual C initial TCLVAR: %s port=%u",boards[b],c);
            expect(label,nwrite==1 && writes[0]==(b==2 && c==AIROHA_PCS_ETH ? 5u:3u));
        }
    }
    return test_errors ? EXIT_FAILURE : EXIT_SUCCESS;
}
'''
    # The bad baseline lacks the board guard, leaving its mock helper unused.
    # Allow exactly that warning so semantic failures, not warning policy, fail it.
    with tempfile.TemporaryDirectory(prefix='xr-pcs-test-') as temp:
        cfile = Path(temp)/'harness.c'
        binary = Path(temp)/'harness'
        cfile.write_text(source)
        cmd=[args.cc,'-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function','-O2',str(cfile),'-o',str(binary)]
        build=subprocess.run(cmd,text=True,capture_output=True)
        if build.returncode:
            print(build.stdout+build.stderr,file=sys.stderr)
            check('host C harness compilation', False)
        else:
            check('host C harness compilation', True)
            run=subprocess.run([str(binary)],text=True,capture_output=True)
            print(run.stdout,end='',flush=True)
            if run.stderr:
                print(run.stderr,file=sys.stderr)
            check('extracted-source behavioral matrix', run.returncode == 0)
    print(f'Result: {"FAIL" if failures else "PASS"}; {len(failures)} failed gate(s). '
          'Focused host/mock checks only; no kernel build or hardware validation.',flush=True)
    return int(bool(failures))

if __name__=='__main__':
    try:
        sys.exit(main())
    except (OSError,ValueError) as exc:
        print('ERROR '+str(exc),file=sys.stderr)
        sys.exit(2)
