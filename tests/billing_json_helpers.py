def responses_body(text='{"ok": true}', **overrides):
    return {
        "status": "completed",
        "output": [
            {"type": "reasoning"},
            {
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text}],
            },
        ],
        "usage": {"input_tokens": 12, "output_tokens": 34},
        **overrides,
    }
