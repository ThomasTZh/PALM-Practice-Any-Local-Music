/**
 * Component tests for the portable save panel (M2.15, spec §17.5).
 *
 * The panel shows the saved-through revision with a download button, a
 * "newer unsaved changes" note when the working revision is ahead, and
 * the save button with its in-flight and error states.
 */

import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import {
  downloadPortableSave,
  listPortableSaves,
  savePortableProject,
  type PortableSave,
} from '../src/api/portable'
import { PortableSavePanel } from '../src/tracks/PortableSavePanel'

vi.mock('../src/api/portable', () => ({
  listPortableSaves: vi.fn(),
  savePortableProject: vi.fn(),
  downloadPortableSave: vi.fn(),
}))

const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
const ART_ID = '88888888-8888-4888-8888-888888888888'

function save(savedRevision: number): PortableSave {
  return {
    artifactId: ART_ID,
    projectId: PROJECT_ID,
    savedRevision,
    sha256: 'c'.repeat(64),
    byteSize: 400_000,
    downloadFilename: `Song-r${savedRevision}.basseparate`,
    downloadUrl: `/api/v1/portable-downloads/${ART_ID}`,
    createdAt: '2026-01-01T00:00:00Z',
  }
}

function setup(currentRevision = 5) {
  render(<PortableSavePanel projectId={PROJECT_ID} currentRevision={currentRevision} />)
}

describe('PortableSavePanel (M2.15 §17.5)', () => {
  it('shows the empty state when no save exists', async () => {
    vi.mocked(listPortableSaves).mockResolvedValue([])
    setup()
    expect(await screen.findByText(/No portable file saved yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Download/i })).not.toBeInTheDocument()
  })

  it('shows the saved-through revision and a download button', async () => {
    vi.mocked(listPortableSaves).mockResolvedValue([save(5)])
    setup(5)
    expect(await screen.findByText(/Saved through revision 5/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Download/ })).toBeInTheDocument()
    expect(screen.queryByText(/Newer unsaved changes/)).not.toBeInTheDocument()
  })

  it('notes newer unsaved changes when the revision is ahead', async () => {
    vi.mocked(listPortableSaves).mockResolvedValue([save(5)])
    setup(7)
    expect(await screen.findByText(/Newer unsaved changes \(revision 7\)/)).toBeInTheDocument()
  })

  it('saves and shows the new artifact on success', async () => {
    vi.mocked(listPortableSaves).mockResolvedValue([])
    vi.mocked(savePortableProject).mockResolvedValue(save(6))
    const user = userEvent.setup()
    setup(6)
    await screen.findByText(/No portable file saved yet/)

    await user.click(screen.getByRole('button', { name: /Save portable project/ }))

    expect(savePortableProject).toHaveBeenCalledWith(PROJECT_ID)
    expect(await screen.findByText(/Saved through revision 6/)).toBeInTheDocument()
  })

  it('shows the server error message on a failed save', async () => {
    vi.mocked(listPortableSaves).mockResolvedValue([])
    vi.mocked(savePortableProject).mockRejectedValue(
      new Error('essential asset file(s) are missing from the store'),
    )
    const user = userEvent.setup()
    setup()
    await screen.findByText(/No portable file saved yet/)

    await user.click(screen.getByRole('button', { name: /Save portable project/ }))

    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(
      screen.getByText(/essential asset file\(s\) are missing from the store/),
    ).toBeInTheDocument()
  })

  it('downloads the latest save', async () => {
    vi.mocked(listPortableSaves).mockResolvedValue([save(5)])
    vi.mocked(downloadPortableSave).mockResolvedValue(undefined)
    const user = userEvent.setup()
    setup()
    await screen.findByText(/Saved through revision 5/)

    await user.click(screen.getByRole('button', { name: /Download/ }))

    await waitFor(() => expect(downloadPortableSave).toHaveBeenCalledTimes(1))
    expect(vi.mocked(downloadPortableSave).mock.calls[0][0].downloadFilename).toBe(
      'Song-r5.basseparate',
    )
  })

  it('disables the save button while a save is in flight', async () => {
    vi.mocked(listPortableSaves).mockResolvedValue([])
    let resolveSave: (s: PortableSave) => void = () => {}
    vi.mocked(savePortableProject).mockReturnValue(
      new Promise((resolve) => {
        resolveSave = resolve
      }),
    )
    const user = userEvent.setup()
    setup()
    await screen.findByText(/No portable file saved yet/)

    await user.click(screen.getByRole('button', { name: /Save portable project/ }))

    const button = screen.getByRole('button', { name: /Saving…/ })
    expect(button).toBeDisabled()
    resolveSave(save(5))
    await screen.findByText(/Saved through revision 5/)
  })
})
