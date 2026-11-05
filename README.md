You need python3 and an rsync of the I-D archive. You can skip the `brew` line if you already have GNU rsync.

```
brew install rsync
hash -r && rsync --version   # should say "rsync version 3.x", not openrsync

rsync -az --partial --info=progress2 rsync.ietf.org::id-archive/ ./id-archive
```

```
ietf % python3 find_noderivs.py ./id-archive > noderivs.txt

Scanning 182,843 draft revisions...
  25,000 done, 1,250 restricted
  50,000 done, 2,516 restricted
  75,000 done, 3,837 restricted
  100,000 done, 5,218 restricted
  125,000 done, 6,489 restricted
  150,000 done, 7,703 restricted
  175,000 done, 9,148 restricted

Total: 9,577 restricted revisions across 2,680 drafts
  other                          7,633
  except-rfc                     1,222
  id-only                        515
  rfc2026-opt-out                207
```
