# News fragments

Each change that users should hear about gets a file in this directory, named `<id>.<type>.md`. At release time, towncrier collects the fragments into a dated section of `CHANGELOG.md` and deletes them; the fragments themselves carry no date.

The `<type>` is one of:

| Type | Section in `CHANGELOG.md` |
|---|---|
| `breaking` | Breaking Changes |
| `added` | Added |
| `changed` | Changed |
| `deprecated` | Deprecated |
| `removed` | Removed |
| `fixed` | Fixed |
| `security` | Security |

Use `breaking` for any change that is not backward compatible and is not simply a removal, such as a changed signature or behaviour; use `changed` for compatible changes.

The `<id>` is the number of the issue or pull request, which the changelog shows as `(#42)`. A fragment with no issue takes an id starting with `+`, such as `+ignore-comment`, and shows no reference.

The file usually holds one line of prose describing the change from the user's side:

```text
release-notes/42.fixed.md
-> A handler that raises on every path no longer counts as unlogged.
```

To preview the collated section without changing anything:

```shell
uv run towncrier build --draft --version <version>
```
