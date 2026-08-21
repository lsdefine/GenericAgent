import { RadioGroup, Radio } from '@douyinfe/semi-ui';
import { useSettingsStore } from '../../stores/settings';

export function LanguageSection() {
  const lang = useSettingsStore((s) => s.lang);
  const setLang = useSettingsStore((s) => s.setLang);

  return (
    <div className="ga-set-block">
      <div className="ga-set-sec-t">语言</div>
      <RadioGroup
        type="button"
        value={lang}
        onChange={(e) => setLang(e.target.value as 'zh' | 'en')}
      >
        <Radio value="zh">简体中文</Radio>
        <Radio value="en">English</Radio>
      </RadioGroup>
    </div>
  );
}
