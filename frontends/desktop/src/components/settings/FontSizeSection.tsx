import { Slider } from '@douyinfe/semi-ui';
import { useSettingsStore } from '../../stores/settings';

export function FontSizeSection() {
  const chatFontSize = useSettingsStore((s) => s.chatFontSize);
  const setChatFontSize = useSettingsStore((s) => s.setChatFontSize);

  return (
    <div className="ga-set-block">
      <div className="ga-set-sec-t">字体大小</div>
      <div className="ga-font-slider-row">
        <Slider
          min={10}
          max={20}
          step={1}
          value={chatFontSize}
          onChange={(val) => setChatFontSize(val as number)}
          style={{ flex: 1 }}
        />
        <span className="ga-font-value">{chatFontSize}px</span>
      </div>
    </div>
  );
}
