# Map and normalize (GitHub Issues)

| Plan field | Lands in |
| --- | --- |
| title | Issue title |
| key | Key label `gw:<last 10 of plan id>:<task id>` (and the full key at the end of the owned body) |
| phase | Label `gw-phase:<phase id>` |
| role | Label `gw-role:<role key>` |
| kind | Label `gw-kind:<kind>` |
| points | `field_map.points` Projects field, else label `points:1` |
| hours, parallel group, depends_on, waits_on, steps, acceptance criteria, verify, done today, visible result | The owned body rendered by the core's `render_proposal.py task` |
| dependencies | "Blocked by" dependencies to the dependency's issue |
| not-ready | The overlay's `not_ready` label |
| plan-owned hash | Not stored on the item; the core keeps it in the manifest |

## normalize

To read an item back for the plan-owned hash, return `{title, body_owned, role_key, phase, key}`:

- `title`: the issue title.
- `body_owned`: the text from `<!-- groundwork:owned:start -->` to `<!-- groundwork:owned:end -->` inclusive, as returned by the API, with `\r\n` turned into `\n`. Leave ticked steps (`- [x]`) as they are; the core's hash treats them as unticked, so ticking a step is never drift. If either marker is missing, return an empty string (that is drift).
- `role_key` and `phase`: from the `gw-role:` and `gw-phase:` labels.
- `key`: the full key from the owned body's last line, which must agree with the key label.

Then run the core's `check_hashes.py owned` on that JSON.
