# Changelog

Release entries are generated from local git history and finalized during
release closeout. Generate a draft with:

```bash
python scripts/generate-release-notes.py --from <previous-release-ref> --to <release-ref> --output release-notes.md
```

Copy the finalized notes into this file or attach them to the GitHub Release,
and record the deployed image digest in the operations log.

## Unreleased

- Pending release notes are generated during the next release.
