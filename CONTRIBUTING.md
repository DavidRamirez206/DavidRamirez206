# Contributing

Thanks for your interest! This repository powers the GitHub profile of
**Ismael Barrionuevo** ([@DavidRamirez206](https://github.com/DavidRamirez206)),
so most of its content is personal. Contributions to the generator are welcome.

## Good contributions

- Bug fixes in `scripts/update_readme.py` or the workflow.
- Better icon sources for languages or tools that currently fall back to a drawn icon.
- Accessibility or rendering improvements for light and dark themes.

Changes to the personal text (About, Education, taglines) are not accepted.

## How it works

`scripts/update_readme.py` runs weekly in GitHub Actions. It reads language data
through the GitHub GraphQL API, draws the banner and the languages card,
downloads icons in dark and light variants, and rewrites the README blocks
between the `START`/`END` markers. Each job commits only when its output changes.

## Workflow

1. Fork the repository and create a branch from `main`.
2. Keep the generator dependency-free: Python standard library only.
3. Make sure two consecutive runs over the same data produce no diff.
4. Use [Conventional Commits](https://www.conventionalcommits.org/) for messages,
   for example `fix: keep tool order stable`.
5. Open a pull request describing what changed and why.

## Running locally

```bash
export METRICS_TOKEN=<a personal access token with repo, read:org and read:user>
python scripts/update_readme.py
git status   # review the generated changes
```

Never commit a token.

## License

By contributing, you agree that your contributions are licensed under the
[MIT License](LICENSE).
