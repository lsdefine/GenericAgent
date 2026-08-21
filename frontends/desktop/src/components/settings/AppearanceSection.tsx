import { RadioGroup, Radio } from '@douyinfe/semi-ui';
import { useSettingsStore } from '../../stores/settings';

export function AppearanceSection() {
  const appearance = useSettingsStore((s) => s.appearance);
  const setAppearance = useSettingsStore((s) => s.setAppearance);

  return (
    <div className="ga-set-block">
      <div className="ga-set-sec-t">外观</div>
      <RadioGroup
        type="button"
        value={appearance}
        onChange={(e) => setAppearance(e.target.value as 'light' | 'dark')}
      >
        <Radio value="light">浅色</Radio>
        <Radio value="dark">深色</Radio>
      </RadioGroup>
    </div>
  );
}
