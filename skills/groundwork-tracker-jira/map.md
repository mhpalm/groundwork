# Map and normalize (Jira Cloud)

| Plan field | Lands in |
| --- | --- |
| title | `summary` |
| key | Key label (or the mapped key field) and the full key at the end of the owned description |
| work_type | Issue type `field_map.work_types.story` or `.task` (default Story and Task) |
| phase | Label `gw-phase-<phase id>`, and the fix version named by the write list's `ensure_release` when `field_map.phase_release` is `version` |
| role | Label `gw-role-<role key>` |
| kind | Label `gw-kind-<kind>` |
| points | `field_map.points` field, always 1 |
| hours | `timetracking.originalEstimate` as `<hours>h` |
| steps, acceptance criteria, verify, done today, visible result, waits_on | The owned description, converted from the core's rendered Markdown by `scripts/jira_body.py` (see Body format) |
| dependencies | `Blocks` links from the dependency to the task |
| not-ready | The overlay's `not_ready` label |

## Body format

People read these issues in Jira, so the owned description is written as Jira formatting, not Markdown text. `scripts/jira_body.py adf BODY.md` gives the ADF for REST, and `scripts/jira_body.py html BODY.md` gives the same body as HTML for the Atlassian connector (`contentFormat: html`). Never write the core's Markdown as text, and never write an empty paragraph as a spacer.

| Core Markdown | Jira |
| --- | --- |
| A line that is only `**Label**` | Heading, level 4 |
| Consecutive plain lines | One paragraph, lines joined by hard breaks |
| `- ` lines | Bullet list |
| `- [ ] ` lines | Task list (the steps checklist) |
| `\| a \| b \|` lines with a `\| --- \|` row | Table with a header row |
| `---` | Rule |
| `**bold**`, `` `code` `` and bare web addresses | Strong, code and link marks |
| The **Type** and **Depends on** lines | Not shown in the description: type, role, estimate, points and phase are Jira fields and labels, and dependencies are Blocks links, so these lines move into the details expand |
| The two owned markers, the key line and the lines after it | Not shown as text: the key, overlay and stamps lines go in a collapsed expand titled "Groundwork details", which ends the owned section |

The owned section is the description from the top through that expand; anything a person adds below it is theirs and is kept on every update. `jira_body.py check BODY.md` confirms the round trip is exact; when it is not, both writers fall back to the 1.0.0 form (one paragraph per line, markers as text), so a stored owned hash can always be recomputed.

## normalize

Return `{title, body_owned, role_key, phase, key}`:

- `title`: `summary`.
- `body_owned`: `scripts/jira_body.py read FILE`, where FILE is the description as ADF (REST) or as the connector returns it. The connector returns Markdown even when HTML is asked for, and flattens the details expand into plain paragraphs with its title dropped (verify); the reader finds the details again by the key line, so the field lines, key, overlay and stamps all read back in place. It rebuilds exactly the Markdown the core rendered, markers included: ticked steps read back as `- [ ] ` so a person ticking steps is not drift, blank paragraphs are skipped, and any node Groundwork never writes inside the owned section reads as drift. Bodies in the 1.0.0 form are read too. No "Groundwork details" expand and no markers give an empty string.
- `role_key`, `phase`: from the labels.
- `key`: from the owned description's last line; it must agree with the key label.

Then run the core's `check_hashes.py owned`. Round-trip and mutation tests for this conversion live in `tests/unit/test_jira_body.py`.
