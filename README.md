# Asyntai AI Chatbot for Sublime Text

Ask your website's AI chatbot from Sublime Text, read your visitors' chats, leads and tickets, and add the docs you write to your chatbot's knowledge base without leaving the editor.

[Asyntai](https://asyntai.com) is an AI chatbot for websites. It answers your visitors from your own pages and documents, collects leads, and hands chats over to your team.

## What you can do

- **Ask My Chatbot**: type a question and see the answer your visitors get. Ask a follow-up in the same tab to continue the conversation.
- **Ask About Selection**: select text and ask your chatbot about it.
- **Add to Knowledge Base**: send the file you are writing, or the selected text, to your chatbot's knowledge base. Your chatbot then uses it in answers. If the file is already there, you can replace it.
- **Recent Chats, Leads, Tickets**: pick one from the list to read the whole conversation in a tab.
- **Open Dashboard**: open your Asyntai dashboard in the browser.

## Setup

1. Install **Asyntai AI Chatbot** with Package Control.
2. Open the Command Palette (`Ctrl+Shift+P`, or `Cmd+Shift+P` on macOS) and run **Asyntai: Set API Key**.
3. Paste the API key from your Asyntai dashboard (Settings, API). The package checks the key before it saves it.

Every command starts with `Asyntai:` in the Command Palette. To add your own key binding, see "Key bindings" below.

The API needs an Asyntai account on the Starter plan or higher.

## Commands

| Command | What it does |
| --- | --- |
| Asyntai: Ask My Chatbot | Ask a question. In an answer tab, it asks a follow-up. |
| Asyntai: Ask My Chatbot (New Conversation) | Start a new conversation in a new tab. |
| Asyntai: Ask About Selection | Ask with the selected text. |
| Asyntai: Add to Knowledge Base | Add this file, or the selection, to your knowledge base. |
| Asyntai: Recent Chats | Your latest website conversations. |
| Asyntai: Leads | Visitors who left an email address or a phone number. |
| Asyntai: Tickets | Chats your chatbot handed over to your team. |
| Asyntai: Open Dashboard | Open the Asyntai dashboard. |
| Asyntai: Set API Key / Sign Out | Add or remove your API key. |

## Key bindings

The package adds no key bindings, so it never overrides yours. To add one, open **Preferences > Key Bindings** and add, for example:

```json
{ "keys": ["ctrl+alt+a"], "command": "asyntai_ask" },
{ "keys": ["ctrl+alt+k"], "command": "asyntai_add_to_knowledge_base" }
```

## Guide

Full guide: https://asyntai.com/documentation/integrations/sublime-text/

## License

MIT
