// frontend/src/components/ConversionPage.tsx
import { useConversion } from '../hooks/useConversion'
import { ConfigPanel } from './conversion/ConfigPanel'
import { StatusPanel } from './conversion/StatusPanel'

export function ConversionPage() {
  const {
    profileNames, selectedProfile, profileData, mountedRepos, saving,
    watchStatus, jobs,
    loadProfile, saveProfile, deleteProfile,
    startWatch, stopWatch, runOnce,
    setProfileData,
  } = useConversion()

  const handleStartWatch = () => {
    if (!selectedProfile) return
    void startWatch(selectedProfile)
  }

  const handleRunOnce = () => {
    if (!selectedProfile) return
    void runOnce(selectedProfile)
  }

  return (
    <div className="conversion-page">
      <ConfigPanel
        profileNames={profileNames}
        selectedProfile={selectedProfile}
        profileData={profileData}
        mountedRepos={mountedRepos}
        saving={saving}
        onProfileSelect={loadProfile}
        onProfileChange={setProfileData}
        onSave={saveProfile}
        onDelete={deleteProfile}
      />
      <StatusPanel
        watchStatus={watchStatus}
        jobs={jobs}
        selectedProfile={selectedProfile}
        onStartWatch={handleStartWatch}
        onStopWatch={() => void stopWatch()}
        onRunOnce={handleRunOnce}
      />
    </div>
  )
}
