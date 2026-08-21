import { useCallback, useEffect } from 'react';
import { useConductorStore } from '../../stores/conductor';
import { useSettingsStore } from '../../stores/settings';
import { Composer } from '../chat/Composer';
import { ModelSelector } from '../chat/Composer/ModelSelector';
import type { SendOptions } from '../../stores/chat';

export function CollabComposer() {
  const sendMessage = useConductorStore((s) => s.sendMessage);
  const conductorTyping = useConductorStore((s) => s.conductorTyping);
  const connectionStatus = useConductorStore((s) => s.connectionStatus);
  const modelConfig = useConductorStore((s) => s.modelConfig);
  const runtimeModel = useConductorStore((s) => s.runtimeModel);
  const loadModel = useConductorStore((s) => s.loadModel);
  const selectModel = useConductorStore((s) => s.selectModel);
  const defaultModelNo = useSettingsStore((s) => s.defaultModelNo);

  useEffect(() => { loadModel(); }, [loadModel]);

  const handleSend = useCallback((text: string, opts?: SendOptions) => {
    const files = opts?.files?.map((f) => ({ name: f.name, path: f.path }));
    const images = opts?.images?.map((f) => ({ name: f.name, path: f.path, base64: f.base64 }));
    sendMessage(text, files, images);
  }, [sendMessage]);

  const handleStop = useCallback(() => {
    // Conductor doesn't support cancel — noop
  }, []);

  const disabled = connectionStatus !== 'ready';
  const selectedNo = modelConfig?.effective ?? modelConfig?.configured ?? defaultModelNo;

  return (
    <div className="collab-composer-wrap" data-slot="collab-composer" data-disabled={disabled || undefined}>
      <Composer
        onSend={handleSend}
        onStop={handleStop}
        isGenerating={conductorTyping}
        hideStatusStack
        modelControl={(
          <ModelSelector
            selectedNo={selectedNo}
            runningNo={runtimeModel?.running ? runtimeModel.effective : null}
            isRunning={!!runtimeModel?.running}
            onSelect={selectModel}
          />
        )}
      />
    </div>
  );
}
