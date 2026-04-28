"use client";

import dynamic from "next/dynamic";

const Editor = dynamic(() => import("@monaco-editor/react"), { ssr: false });

export function JsonInspector({ value }: { value: unknown }) {
  return (
    <div className="json-panel">
      <Editor
        language="json"
        theme="vs-light"
        value={JSON.stringify(value, null, 2)}
        options={{
          readOnly: true,
          minimap: { enabled: false },
          fontSize: 12,
          scrollBeyondLastLine: false,
          wordWrap: "on"
        }}
      />
    </div>
  );
}
