# Ticket and graph inputs

Use a tracer bullet for each ticket. A mechanical cross-cutting migration can
expand an interface, migrate end-to-end slices and contract it at the end.
Separate enabling cleanup when it truly blocks work. Read exact links across
versions when needed. Releases and live checks stay in version order.

Write the issue body with Parent, What to build, Owned paths, Links, Acceptance
criteria and Proof. Parent ends with the size, exactly once: `Size: S.`, `Size: M.`
or `Size: L.`. In Owned paths give each exact file or folder in backticks, with
`in \`owner/repo\`` when it is another repository's.
Mark a small shared file `(shared)` and name the separate lines each ticket
owns. `**Relies on:**` lists exact backticked interface-file paths on one line,
or `nothing`. Use `## Done by` for a person's ticket. Proof names the spec
claim and how to show it, red first.

Use the [Plan links contract](../../contracts/plan-links.v1.md) for each native
blocker's `real` behavior or exceptional `file` reason. Include external
blockers. Use GitHub CLI 2.94 or later and body files. Create each ticket with
`gh issue create --parent <spec> --milestone <version> --body-file <file>`
and pass `--blocked-by` only when there are blockers. On an uncertain write,
find and read back the effect first. Check the sub-issue count and every
read-back title, body, parent, milestone, label and native blocker.

Run `sh "<this skill's folder>/check-relies.sh" --root . < ticket.md` after a successful body
read from GitHub. When a declared interface file is not yet written, allow
its exact path with `--planned` only after verifying the blocking ticket owns it.
The dependent's start still requires the file. `sh "<this skill's folder>/check-links.sh" <spec>`
must separately pass. Keep the link report and explain each file link.

## Picture data

Build the diagram input from the same proposal or verified issue graph shown
in the table. Keep the reasons public-safe. Example:

```json
{
  "tickets": [
    {"id": "#10", "title": "Write the report contract", "size": "S", "state": "merged", "role": "external"},
    {"id": "#11", "title": "Show the report", "size": "M", "state": "building", "role": "builder"},
    {"id": "#12", "title": "Confirm the pilot", "size": "S", "state": "waiting", "role": "jake"}
  ],
  "links": [
    {"blocker": "#10", "ticket": "#11", "kind": "real", "reason": "Report fields"},
    {"blocker": "#11", "ticket": "#12", "kind": "real", "reason": "Pilot to try"}
  ]
}
```

Use proposal IDs before issue numbers exist, `external` for a blocker outside
the spec and `release` for Jake's release go. Include the version in an external
blocker's title. Use verified merge evidence for `merged`, an existing builder
for `building` and `waiting` before either. A closed blocker needs independent
merge evidence. When redrawing, read the states fresh and leave the approval
record intact. The critical path is a longest chain of hard links (a `file` link into a
builder's ticket only shares context, F6), including external blockers. If chat cannot render Mermaid, send the rendered picture
inline and retain the Mermaid block on the issue.
