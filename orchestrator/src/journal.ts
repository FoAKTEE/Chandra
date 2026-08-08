/** Append-only JSONL journal — the durable agent-to-agent message log.
 * Same discipline as the Python ledgers: never rewrite, always append. */
import * as fs from "node:fs";
import * as path from "node:path";
import type { JournalEntry, Message } from "./types.js";

export class Journal {
  constructor(readonly filePath: string) {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
  }

  append(msg: Message): JournalEntry {
    const entry: JournalEntry = { at: new Date().toISOString(), msg };
    fs.appendFileSync(this.filePath, JSON.stringify(entry) + "\n", "utf-8");
    return entry;
  }

  read(): JournalEntry[] {
    if (!fs.existsSync(this.filePath)) return [];
    return fs.readFileSync(this.filePath, "utf-8")
      .split("\n")
      .filter(line => line.trim())
      .map(line => JSON.parse(line) as JournalEntry);
  }

  /** Messages of one type, newest last. */
  ofType<T extends Message["type"]>(type: T): Extract<Message, { type: T }>[] {
    return this.read()
      .map(e => e.msg)
      .filter((m): m is Extract<Message, { type: T }> => m.type === type);
  }
}
