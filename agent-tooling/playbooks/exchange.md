# Playbook: moving files between Lodewijk's Mac and the server's agent account

The server (hague) has a one-way exchange at `/srv/exchange` (agent sees it as `~/exchange`):
- `to-agent/`: owned by Lodewijk's own user (`ubuntu`); agent can read, never write. Inbound.
- `from-agent/`: owned by `agent`; Lodewijk's user can read. Outbound.

Agent sessions can't move files across machines. They give Lodewijk the commands below, filled in,
one per block, with the machine each runs on. They never guess paths.

## Mac → agent (inbound), run in Lodewijk's own Terminal on the Mac

```bash
scp -r <local folder> hague:/srv/exchange/to-agent/<name-YYYY-MM-DD>/
```
```bash
ssh hague 'setfacl -R -m u:agent:rX,m:rX /srv/exchange/to-agent/<name-YYYY-MM-DD>'
```
- `hague` is the alias for Lodewijk's own account; `hague-agent` logs in as agent. Copies to the
  Mac side or "done" in some other folder don't count: the agent session checks with
  `ls /srv/exchange/to-agent/<name>` before it starts.
- The `setfacl` line is not optional: an scp'd folder arrives with an ACL mask that hides it from
  agent (agent-tooling/lessons.md "A directory created by scp can have an ACL mask…").
- **No symlinks:** `scp -r` copies what a link points to. A folder with links goes as one archive
  instead (`tar -czf x.tgz -C <parent> <folder>`, scp the .tgz, then `tar -xzf` on the server).
- Large or important packets carry a `SHA256SUMS`; check it as agent:
  `ssh -t hague 'cd /srv/exchange/to-agent/<name> && sudo -u agent sha256sum -c --quiet SHA256SUMS && echo checked'`.

## Agent → Mac (outbound)

The agent session writes into `/srv/exchange/from-agent/<name>/` with a `SHA256SUMS` (relative paths).
Lodewijk pulls it with his own script, from his own Terminal (it refuses inside an agent session):

```bash
python3 ~/agent/bin/hague_pull.py pull <name> --keep
```
It verifies every file and refuses links and odd paths. Leave a still-growing log out of the checksum file.

## Branches (git)

Not through the exchange: the branch-handoff route (`playbooks/branch-handoff.md`, `scripts/handoff.py`).
