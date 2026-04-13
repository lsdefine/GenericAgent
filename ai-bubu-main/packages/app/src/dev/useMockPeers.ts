import { useSocialStore } from '@/stores/social'
import { usePetStore } from '@/stores/pet'
import { useActivityStore } from '@/stores/activity'
import { currentLang } from '@/composables/useI18n'
import type { PeerInfo, MovementState, MoodState, StepRecord } from '@/types'

interface MockDef {
  zh: string
  en: string
  petSkin: string
  movementState: MovementState
  moodState: MoodState
  stepsOffset: number
}

const BASE_PEERS: MockDef[] = [
  {
    zh: '代码喵',
    en: 'CodeCat',
    petSkin: 'mort',
    movementState: 'sprint',
    moodState: 'excited',
    stepsOffset: 1800,
  },
  {
    zh: '冲刺鸟',
    en: 'SprintBird',
    petSkin: 'tard',
    movementState: 'run',
    moodState: 'happy',
    stepsOffset: 900,
  },
  {
    zh: '键盘侠',
    en: 'KeyHero',
    petSkin: 'doux',
    movementState: 'idle',
    moodState: 'sleepy',
    stepsOffset: -100,
  },
  {
    zh: '摸鱼侠',
    en: 'SlackMan',
    petSkin: 'vita',
    movementState: 'walk',
    moodState: 'normal',
    stepsOffset: -1200,
  },
  {
    zh: '咖啡因',
    en: 'Caffeine',
    petSkin: 'tard',
    movementState: 'idle',
    moodState: 'sleepy',
    stepsOffset: -2500,
  },
]

const MOCK_PEERS: MockDef[] = [
  ...Array.from({ length: 6 }, (_, i) => ({
    ...BASE_PEERS[0],
    stepsOffset: BASE_PEERS[0].stepsOffset + i * 200,
  })),
  ...BASE_PEERS.slice(1),
  ...Array.from({ length: 3 }, (_, i) => ({
    ...BASE_PEERS[4],
    stepsOffset: BASE_PEERS[4].stepsOffset - i * 300,
  })),
]

function injectMockInsights(activityStore: ReturnType<typeof useActivityStore>) {
  const today = new Date()
  const history: StepRecord[] = []
  for (let d = 7; d >= 1; d--) {
    const date = new Date(today)
    date.setDate(date.getDate() - d)
    const yyyy = date.getFullYear()
    const mm = String(date.getMonth() + 1).padStart(2, '0')
    const dd = String(date.getDate()).padStart(2, '0')
    const dayOfWeek = date.getDay()
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6
    const baseSteps = isWeekend ? 2000 + Math.random() * 3000 : 8000 + Math.random() * 10000
    const hourly = new Array(24).fill(0)
    for (let h = 9; h <= 22; h++) {
      if (h >= 12 && h <= 13) {
        hourly[h] = Math.floor(Math.random() * 50)
      } else if (h >= 9 && h <= 11) {
        hourly[h] = Math.floor(200 + Math.random() * 500)
      } else if (h >= 14 && h <= 18) {
        hourly[h] = Math.floor(300 + Math.random() * 600)
      } else {
        hourly[h] = Math.floor(50 + Math.random() * 200)
      }
    }

    history.push({
      date: `${yyyy}-${mm}-${dd}`,
      steps: Math.floor(baseSteps),
      peakScore: Math.floor(60 + Math.random() * 40),
      activeMinutes: Math.floor(60 + Math.random() * 180),
      hourlySteps: hourly,
      providerMinutes: {
        cursor: Math.floor(30 + Math.random() * 120),
        'claude-code': Math.floor(10 + Math.random() * 80),
        trae: Math.floor(Math.random() * 30),
      },
    })
  }
  for (const record of history) {
    activityStore.addHistoryRecord(record)
  }

  const todayHourly = activityStore.hourlySteps
  const now = new Date().getHours()
  for (let h = 9; h <= Math.min(now, 22); h++) {
    if (todayHourly[h] === 0) {
      if (h >= 12 && h <= 13) {
        todayHourly[h] = Math.floor(Math.random() * 30)
      } else {
        todayHourly[h] = Math.floor(100 + Math.random() * 400)
      }
    }
  }

  if (!activityStore.providerMinutes['cursor']) {
    activityStore.providerMinutes['cursor'] = Math.floor(40 + Math.random() * 80)
    activityStore.providerMinutes['claude-code'] = Math.floor(20 + Math.random() * 60)
  }

  activityStore.updatePeak(85)
}

// Recording presets — press Shift+number to activate a full scenario
interface RecordingPreset {
  label: string
  movement: MovementState
  score: number
  mood: MoodState
  steps: number
}

const RECORDING_PRESETS: RecordingPreset[] = [
  { label: '🧘 idle + normal', movement: 'idle', score: 0, mood: 'normal', steps: 500 },
  { label: '💤 idle + sleepy', movement: 'idle', score: 0, mood: 'sleepy', steps: 500 },
  { label: '🚶 walk + normal', movement: 'walk', score: 35, mood: 'normal', steps: 3000 },
  { label: '🏃 run + normal', movement: 'run', score: 65, mood: 'normal', steps: 8000 },
  { label: '🔥 sprint + excited', movement: 'sprint', score: 95, mood: 'excited', steps: 16000 },
  {
    label: '🎬 peer escort (many peers, high steps)',
    movement: 'run',
    score: 70,
    mood: 'normal',
    steps: 12000,
  },
]

export function startMockPeers() {
  const socialStore = useSocialStore()
  const petStore = usePetStore()
  const activityStore = useActivityStore()

  function inject() {
    const isZh = currentLang.value === 'zh'
    const mySteps = petStore.dailySteps
    MOCK_PEERS.forEach((def, i) => {
      const peer: PeerInfo = {
        peerId: `mock-peer-${i}`,
        nickname: isZh ? def.zh : def.en,
        dailySteps: Math.max(0, mySteps + def.stepsOffset),
        activityScore:
          def.movementState === 'sprint'
            ? 95
            : def.movementState === 'run'
              ? 60
              : def.movementState === 'walk'
                ? 30
                : 5,
        movementState: def.movementState,
        moodState: def.moodState,
        petSkin: def.petSkin,
        lastSeen: Date.now(),
        isOnline: true,
      }
      socialStore.updatePeer(peer)
    })
  }

  inject()
  injectMockInsights(activityStore)
  petStore.addSteps(6000)

  const timer = setInterval(inject, 5000)

  const MOOD_KEYS: Record<string, MoodState> = {
    '1': 'normal',
    '2': 'sleepy',
    '3': 'excited',
    '4': 'happy',
  }

  const MOVEMENT_KEYS: Record<string, { movement: MovementState; score: number }> = {
    '5': { movement: 'idle', score: 0 },
    '6': { movement: 'walk', score: 35 },
    '7': { movement: 'run', score: 65 },
    '8': { movement: 'sprint', score: 95 },
  }

  const INTERACTION_KEYS: Record<string, 'pat' | 'poke'> = {
    p: 'pat',
    o: 'poke',
  }

  function onKey(e: KeyboardEvent) {
    if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return

    if (e.shiftKey && e.key >= '1' && e.key <= '6') {
      const idx = parseInt(e.key) - 1
      const preset = RECORDING_PRESETS[idx]
      petStore.setMovement(preset.movement, preset.score)
      petStore.setMood(preset.mood)
      petStore.dailySteps = preset.steps
      console.warn(`[Mock] 🎬 preset ${e.key}: ${preset.label}`)
      return
    }

    const mood = MOOD_KEYS[e.key]
    if (mood) {
      petStore.setMood(mood)
      console.warn(`[Mock] mood → ${mood}`)
      return
    }

    const mv = MOVEMENT_KEYS[e.key]
    if (mv) {
      petStore.setMovement(mv.movement, mv.score)
      console.warn(`[Mock] movement → ${mv.movement} (score: ${mv.score})`)
      return
    }

    const interaction = INTERACTION_KEYS[e.key]
    if (interaction) {
      petStore.playInteraction(interaction)
      console.warn(`[Mock] interaction → ${interaction}`)
      return
    }
  }
  window.addEventListener('keydown', onKey)

  console.warn(
    `[Mock] ✅ ${MOCK_PEERS.length} peers + insights data injected\n` +
      '  1-4: mood (normal/sleepy/excited/happy)\n' +
      '  5-8: movement (idle/walk/run/sprint)\n' +
      '  p/o: interaction (pat/poke)\n' +
      '  Shift+1~6: recording presets\n' +
      RECORDING_PRESETS.map((p, i) => `    Shift+${i + 1}: ${p.label}`).join('\n'),
  )
  return () => {
    clearInterval(timer)
    window.removeEventListener('keydown', onKey)
  }
}
