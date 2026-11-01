---
name: check-claims
description: Check every cited claim in a manuscript (.docx) against the cited sources' own text with refaudit — one claim-judge subagent per source plus blind second opinions — and write <stem>_claims.xlsx, a commented .docx and a JSON file.
argument-hint: "<manuscript.docx> [--sources DIR] [--model M] [--effort E] [--out DIR] [--force]"
disable-model-invocation: true
allowed-tools: Bash(refaudit claims *) Read Glob Agent(claim-judge) Agent(claim-second-opinion)
---

# Check the claims in a manuscript

Arguments: `$ARGUMENTS`

Parse them: the first argument is the manuscript (.docx). Options: `--sources DIR` (the user's PDFs, EPUBs, DOCX,
HTML or TXT files, any names), `--model M` (default `fable`), `--effort E` (default `max`), `--out DIR`, `--force`.
Paths may point anywhere on the user's disk; in a cloud session the files must be committed under `inputs/`.

Run every step below in order. The `refaudit claims` commands are deterministic; only the subagents judge.
Never judge claims yourself and never pass a first verdict to a second-opinion judge.

## 1. Prepare

```
refaudit claims prepare "<manuscript>" [--sources "<DIR>"] [--out "<DIR>"] [--force]
```

Progress goes to stderr; the last line of stdout is the **work folder** (`<stem>_claims`). If prepare reports
blocked hosts or API failures, tell the user which hosts, and carry on.

## 2. First judgments

```
refaudit claims status "<work folder>"
```

The JSON lists `to_judge` (refkeys) and, under `sources`, each source's `packet`, `verdicts` path and `pending`
claim IDs. For every refkey in `to_judge`, launch the **claim-judge** subagent with the Agent tool
(`subagent_type: "claim-judge"`, `model: <model>`, `effort: <effort>`) and this prompt:

> Packet: `<packet>`. Judge these claims: `<pending IDs>`. Write `<verdicts path>`. Work folder: `<work folder>`.

Run them in parallel batches of **at most five** (one message with up to five Agent calls), and wait for each
batch before starting the next. A judge that fails is not fatal: its claims stay "not judged" in the report.

## 3. Check the verdicts

```
refaudit claims verify "<work folder>"
```

This checks every evidence quote against the source text, compares page locators and quotations, lists the numbers
found, and decides which claims need a second opinion (every row that isn't GREEN, every low-confidence row and a
random 10% of GREEN rows). If it reports problems in a verdict file, launch that source's judge again once with the
problem in the prompt.

## 4. Second opinions

First hide the first verdicts, so the second judges cannot see them even where hooks are not enforced:

```
refaudit claims seal "<work folder>"
```

Run `refaudit claims status "<work folder>"` again. For every refkey in `to_second`, launch the
**claim-second-opinion** subagent (`subagent_type: "claim-second-opinion"`, same `model` and `effort`) with:

> Packet: `<packet>`. Judge these claims: `<second_pending IDs>`. Write `<second path>`. Work folder: `<work folder>`.

Same batches of at most five. Then run `refaudit claims verify "<work folder>"` once more; it brings the first
verdicts back and compares the two opinions.

## 5. Report

```
refaudit claims report "<work folder>" --model <model> --effort <effort> [--out "<DIR>"]
```

Then tell the user, briefly:
- where the three files are (`<stem>_claims.xlsx`, `<stem>_claims_comments.docx`, `<stem>_claims.json`);
- the counts by status, and the CRITICAL and MAJOR problems (claim ID, citation, verdict, one-line explanation);
- the sources listed on the **PDFs to upload** sheet (evidence ABSTRACT, PREPRINT or NONE): adding those PDFs to
  the sources folder and running `/check-claims` again re-judges only the sources whose text changed
  (`--force` re-judges everything).
