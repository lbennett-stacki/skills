---
name: read-aloud
description: Read something aloud with high-quality TTS (OpenAI gpt-4o-mini-tts by default, ElevenLabs on request). Works on anything Claude can read, such as a Notion page, a Granola meeting, a Slack thread or channel, a Gmail thread, a web page, a local file, or Claude's own last reply. Claude rewrites the source as a script meant for the ear, then synthesises and plays an MP3 saved to ~/Music/read-aloud/. Use when the user asks to read, listen to, narrate, "TTS", or "read this to me", or wants an audio version of a doc, meeting, thread, email or article.
---

# Read aloud

The user wants to listen to things instead of reading them.

## Steps

1. **Get the source text.** Use whatever tool reaches it:

   | Source | How to read it |
   | --- | --- |
   | Notion page | `notion-fetch` on the URL or ID, or `notion-search` first for a title. Check `truncated` and `unknown_block_ids`. |
   | Granola meeting | `list_meetings` or `query_granola_meetings` to find it, then the meeting's notes. Fetch `get_meeting_transcript` only when the user asks for the transcript. |
   | Slack | `slack_read_thread` for a thread link, `slack_read_channel` for recent channel messages. |
   | Email | Gmail `search_threads`, then `get_thread`. |
   | Web page | `WebFetch` with a prompt asking for the full article text, not a summary. |
   | File or pasted text | Read it directly. |

   If part of the source was cut off or unreadable, say so in the reply.

2. **Write a listening script** to `<scratchpad>/<slug>.txt`. A listener can't see the source, so rewrite it for the ear rather than stripping markup:
   - Open with what it is ("The Slack thread in #eng about the deploy, from Tuesday.").
   - Headings become spoken transitions ("Next, the rollout plan.").
   - Lists become sentences. Keep every item. Don't summarise unless the user asks.
   - Tables: describe what the table compares, then read the rows that matter as sentences. Say how many rows you skipped.
   - Code, diagrams and embeds: one sentence on what each shows. Never read code character by character.
   - Links and mentions: read the display text only. Drop URLs and markup.
   - Chat and email: name each speaker before their message, use first names, and give times only when they matter. Drop signatures, quoted reply chains, emoji reactions and bot noise.
   - Web pages: read the article. Skip navigation, cookie banners, ads and footers.
   - Expand abbreviations a voice would stumble on the first time they appear.
   - Separate paragraphs with a blank line. The script splits on blank lines.

3. **Synthesise.** Run it in the background so the user hears chunk one while later chunks render:
   ```bash
   python3 <this skill's base directory>/speak.py <scratchpad>/<slug>.txt
   ```
   Flags: `--provider eleven` for ElevenLabs, `--speed 1.15` to speed up, `--no-play` to only save the file, `--name` to set the output stem. Playback uses macOS `afplay`; elsewhere pass `--no-play` and hand back the file.

4. **Reply** with the saved path, duration (`afinfo <file> | grep duration` on macOS), and anything left out of the script.

## Configuration

Environment variables, all optional:

- `READ_ALOUD_PROVIDER`: `openai` (default) or `eleven`.
- `READ_ALOUD_OPENAI_VOICE`: default `coral`. Others include `alloy`, `ash`, `ballad`, `echo`, `sage`, `shimmer`, `verse`.
- `READ_ALOUD_ELEVEN_VOICE`: voice ID, default George (`JBFqnCBsd6RMkjVDRZzb`).
- `READ_ALOUD_OPENAI_MODEL`, `READ_ALOUD_ELEVEN_MODEL`.
- `READ_ALOUD_ENV_FILES`: extra `KEY=value` files to read keys from, colon-separated, for a key that already lives in some project's `.env`.

Keys (`OPENAI_API_KEY`, `ELEVENLABS_API_KEY`) are read from the shell environment first, then `~/.config/read-aloud/env`, then `READ_ALOUD_ENV_FILES`.

## Putting audio back in Notion

Only when the user explicitly asks, because it changes a shared page that teammates see. Upload the MP3 with `notion-create-file-upload`, then add the upload's `suggested_markdown` (an `<audio>` block) at the top of the page with `notion-update-page`.
