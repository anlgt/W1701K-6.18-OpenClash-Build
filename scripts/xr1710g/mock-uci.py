#!/usr/bin/env python3
"""Host-only strict UCI subset emulator; never shipped to router."""
import os,sys,shlex,json,pathlib
args=sys.argv[1:]; root=pathlib.Path(os.environ['XR_MIGRATION_ROOT']); conf=root/'etc/config'; staged=False
while args and args[0].startswith('-'):
 opt=args.pop(0)
 if opt in ('-q','-N'): continue
 if opt in ('-c','-t'):
  val=args.pop(0)
  if opt=='-c': conf=pathlib.Path(val); staged=True
 else: sys.exit(92)
if not args: sys.exit(93)
command=args[0]; package=args[1] if len(args)>1 else ''
with (root/'uci-calls.jsonl').open('a') as f: f.write(json.dumps({'args':sys.argv[1:], 'staged':staged})+'\n')
if command=='changes':
 if (root/'pending').exists(): print('network.wan.device=changed')
 sys.exit(0)
if command!='export' or package not in ('network','firewall'): sys.exit(94)
if staged and (root/'reject-staged').exists(): sys.exit(1)
s=(conf/package).read_text()
lex=shlex.shlex(s,posix=True,punctuation_chars='\n');lex.whitespace=' \t\r';lex.whitespace_split=True
rows=[];row=[]
for token in lex:
 if token and set(token)=={'\n'}:
  if row: rows.append(row);row=[]
 else: row.append(token)
if row: rows.append(row)
current=False
for row in rows:
 if row[0]=='config' and len(row) in (2,3): current=True
 elif row[0] in ('option','list') and len(row)==3 and current: pass
 elif row[0]=='package' and row==['package',package]: pass
 else: print('invalid mock UCI row: '+repr(row),file=sys.stderr);sys.exit(1)
print('package '+package+'\n')
for row in rows:
 if row[0]=='package': continue
 print(' '.join(shlex.quote(v) for v in row))
if staged and (root/'concurrent').exists():
 with (root/'etc/config/network').open('a') as f: f.write('\n# concurrent user edit\n')
