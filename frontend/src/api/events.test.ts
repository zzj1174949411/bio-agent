import { describe, expect, it } from "vitest";
import { appendEvent } from "./events";

describe("event reducer", () => { it("deduplicates replayed events by sequence", () => { const event = {seq:3,kind:"message.delta",payload:{text:"你好"}}; const once=appendEvent([],event); expect(appendEvent(once,event)).toEqual(once); }); });
