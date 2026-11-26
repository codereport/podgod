<img width="1016" height="704" alt="image" src="https://github.com/user-attachments/assets/634c8463-9354-474b-bdf7-28f40dfafd42" />

## Public personality feeds

The version-1 personality index and individual feeds include an optional
`revision` content hash. Matching index and feed revisions let consumers skip
unchanged feeds. Revisions cover episodes and feed metadata, including
corrections that do not change the episode count; `updatedAt` and the revision
field itself are excluded. Existing clients can continue reading the same
`/data/v1/` URLs.

Discovery, profile edits, title edits and artwork generation maintain these
revisions. After editing public feed JSON by hand, refresh the revisions without
running discovery:

```bash
python scripts/personality_revision.py
```
