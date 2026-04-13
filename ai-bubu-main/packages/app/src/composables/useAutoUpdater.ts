import { ref } from 'vue'
import { check } from '@tauri-apps/plugin-updater'
import { relaunch } from '@tauri-apps/plugin-process'

export type UpdateStatus =
  | 'idle'
  | 'checking'
  | 'up-to-date'
  | 'available'
  | 'downloading'
  | 'ready'
  | 'error'

const CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000

const status = ref<UpdateStatus>('idle')
const newVersion = ref('')
const errorMessage = ref('')
const downloadProgress = ref(0)

let updateInstance: Awaited<ReturnType<typeof check>> | null = null
let contentLength = 0
let downloaded = 0
let periodicTimer: ReturnType<typeof setInterval> | null = null

async function checkForUpdate(silent = true) {
  if (status.value === 'checking' || status.value === 'downloading') return
  if (silent && (status.value === 'available' || status.value === 'ready')) return

  status.value = 'checking'
  errorMessage.value = ''
  updateInstance = null

  try {
    const update = await check()
    if (update) {
      updateInstance = update
      newVersion.value = update.version
      status.value = 'available'
    } else {
      updateInstance = null
      if (silent) {
        status.value = 'idle'
      } else {
        status.value = 'up-to-date'
        setTimeout(() => {
          if (status.value === 'up-to-date') status.value = 'idle'
        }, 3000)
      }
    }
  } catch (err) {
    updateInstance = null
    if (!silent) {
      errorMessage.value = String(err)
      status.value = 'error'
    } else {
      status.value = 'idle'
    }
  }
}

function startPeriodicCheck() {
  if (periodicTimer) return
  periodicTimer = setInterval(() => checkForUpdate(true), CHECK_INTERVAL_MS)
}

function stopPeriodicCheck() {
  if (periodicTimer) {
    clearInterval(periodicTimer)
    periodicTimer = null
  }
}

async function downloadAndInstall() {
  if (!updateInstance || status.value === 'downloading') return

  status.value = 'downloading'
  downloadProgress.value = 0
  contentLength = 0
  downloaded = 0

  try {
    await updateInstance.downloadAndInstall((event) => {
      if (event.event === 'Started') {
        contentLength = event.data.contentLength ?? 0
        downloaded = 0
        downloadProgress.value = 0
      } else if (event.event === 'Progress') {
        downloaded += event.data.chunkLength
        if (contentLength > 0) {
          downloadProgress.value = Math.min(99, Math.round((downloaded / contentLength) * 100))
        } else {
          downloadProgress.value = Math.min(downloadProgress.value + 1, 90)
        }
      } else if (event.event === 'Finished') {
        downloadProgress.value = 100
      }
    })
    status.value = 'ready'
  } catch (err) {
    errorMessage.value = String(err)
    status.value = 'error'
  }
}

async function installAndRelaunch() {
  await relaunch()
}

export function useAutoUpdater() {
  return {
    status,
    newVersion,
    errorMessage,
    downloadProgress,
    checkForUpdate,
    downloadAndInstall,
    installAndRelaunch,
    startPeriodicCheck,
    stopPeriodicCheck,
  }
}
