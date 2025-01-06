## pre-commit

We use [pre-commit](https://pre-commit.com/) to maintain consistent coding
style and try to catch errors before they happening with some linting. You'll
need to install pre-commit, and then go to the project root and type
`pre-commit install`. After that, pre-commit will run before every commit and
check for a bunch of common coding issues or anit-patterns, and also do some
reformatting. If there are any changes to the code the commit will abort so you
can check those changes, and if you're happy with them then just do another
commit and it should succeed. If there are linting errors you'll need to correct
them before you can commit.

Config for pre-commit is stored in the `.pre-commit-config.yaml` file.

## Ignore revs

Things like running a new code formatter or linter over the whole codebase can
cause a ton of little changes that we would like to ignore when using commands
like `git blame`. To do this, we keep a list of commits that we'd like to
ignore in the `.git-blame-ignore-revs` file in the project root. You should
tell git about this file using the follwing command:

```
git config blame.ignoreRevsFile .git-blame-ignore-revs
```

This only has to be run once, and afterwards any new commit hashes added to the
`.git-blame-ignore-revs` file will automatically be taken into account.
