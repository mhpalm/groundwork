# Map and normalize (Jira Cloud)

| Plan field | Lands in |
| --- | --- |
| title | `summary` |
| key | Key label (or the mapped key field) and the full key at the end of the owned description |
| phase | Label `gw-phase-<phase id>` |
| role | Label `gw-role-<role key>` |
| kind | Label `gw-kind-<kind>` |
| points | `field_map.points` field, always 1 |
| hours | `timetracking.originalEstimate` as `<hours>h` |
| steps, acceptance criteria, verify, done today, visible result, waits_on | The owned description, converted from the core's rendered Markdown to ADF: each line a paragraph, `- [ ]` lines as an ADF task list, the two owned markers as their own paragraphs |
| dependencies | `Blocks` links from the dependency to the task |
| not-ready | The overlay's `not_ready` label |

## normalize

Return `{title, body_owned, role_key, phase, key}`:

- `title`: `summary`.
- `body_owned`: convert the description's ADF back to the same Markdown the core rendered (paragraph text joined by newlines, task items as `- [ ] ` or `- [x] ` lines, ticked items read back as `- [ ] ` so a person ticking steps is not drift), and keep the lines from the start marker to the end marker inclusive. Missing markers give an empty string.
- `role_key`, `phase`: from the labels.
- `key`: from the owned description's last line; it must agree with the key label.

Then run the core's `check_hashes.py owned`. Mutation tests for this conversion live in the repo's tests.
