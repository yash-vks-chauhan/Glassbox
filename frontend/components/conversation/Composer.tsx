"use client";

import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import { ArrowUp, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = {
  disabled?: boolean;
  onSubmit: (text: string) => void | Promise<void>;
  placeholder?: string;
  suggestions?: string[];
};

export function Composer({ disabled, onSubmit, placeholder, suggestions = [] }: Props) {
  const [value, setValue] = useState("");
  const taRef = useRef<HTMLTextAreaElement | null>(null);

  function resize() {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 280)}px`;
  }

  async function send() {
    const text = value.trim();
    if (!text || disabled) return;
    setValue("");
    if (taRef.current) {
      taRef.current.style.height = "auto";
    }
    await onSubmit(text);
  }

  function onKey(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      send();
    }
  }

  function submitForm(event: FormEvent) {
    event.preventDefault();
    send();
  }

  return (
    <div className="rounded-xl border bg-card p-2 shadow-sm">
      {suggestions.length > 0 && !value ? (
        <div className="flex flex-wrap gap-1.5 px-2 pb-2 pt-1">
          {suggestions.map((s) => (
            <button
              type="button"
              key={s}
              onClick={() => {
                setValue(s);
                setTimeout(() => taRef.current?.focus(), 0);
              }}
              className="inline-flex items-center gap-1.5 rounded-md border bg-background/60 px-2 py-1 text-[11px] text-muted-foreground hover:bg-accent/40 hover:text-foreground"
            >
              <Sparkles className="h-3 w-3" />
              {s}
            </button>
          ))}
        </div>
      ) : null}
      <form onSubmit={submitForm} className="flex items-end gap-2">
        <textarea
          ref={taRef}
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            resize();
          }}
          onKeyDown={onKey}
          rows={1}
          placeholder={placeholder ?? "Ask a question scoped to this client…"}
          disabled={disabled}
          className={cn(
            "min-h-[44px] flex-1 resize-none bg-transparent px-2 py-2 text-[14px] leading-6 outline-none placeholder:text-muted-foreground",
          )}
          aria-label="Conversation composer"
        />
        <Button
          type="submit"
          size="icon"
          disabled={disabled || !value.trim()}
          className="h-9 w-9 shrink-0 rounded-md"
          aria-label="Send"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </form>
      <div className="flex items-center justify-between gap-2 border-t px-2 pt-1.5 text-[10px] text-muted-foreground">
        <span>
          Press <kbd className="rounded border bg-background px-1 font-mono">Enter</kbd> to send,{" "}
          <kbd className="rounded border bg-background px-1 font-mono">Shift</kbd> +{" "}
          <kbd className="rounded border bg-background px-1 font-mono">Enter</kbd> for newline
        </span>
        <span>Every answer is logged with sources, claims, and trust score.</span>
      </div>
    </div>
  );
}
