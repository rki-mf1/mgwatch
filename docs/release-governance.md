# Release Governance

This document describes the release governance controls used for
MetagenomeWatch and the evidence that can be referenced from the
IT-Grundschutz-Check.

## Current operating model

The project currently has one active maintainer. Because the same person would
normally submit and approve each pull request, mandatory independent PR review
is not a realistic control at this team size. This is a documented residual
governance limitation.

Compensating controls are:

- changes are prepared on branches and merged through pull requests when
  practical;
- CI checks must pass before production release;
- release notes are generated from git history and finalized for each release;
- production deployments use immutable image digests;
- rollback digests are captured before rollout;
- deployment evidence is recorded in an operations log or change request.

If a second qualified maintainer becomes available, require at least one
independent approval for production-impacting changes before merge or release.

## Branch protection requirements

Repository administrators should configure `main` branch protection in GitHub
where available:

- prevent force pushes and branch deletion;
- require status checks for the test, lint, image build, and vulnerability scan
  workflows that are relevant to the change;
- require branches to be up to date before merge when practical;
- restrict direct pushes to `main`, except documented emergency admin actions.

These settings live in GitHub repository configuration rather than in this
repository. Verify them periodically and record the verification date or
screenshot location in the operations log.

## Release evidence

For each production release, retain enough evidence to reconstruct what changed
and how it was deployed:

- pull request or merge commit link;
- passing CI run links;
- generated release notes or changelog entry;
- published image digest;
- production deployment digest;
- rollback target digest;
- backup path or confirmation where applicable;
- smoke-test result and log review outcome;
- production change request or operations-log entry.

The [production release checklist](./release-checklist.md) defines the release
steps that collect this evidence.
