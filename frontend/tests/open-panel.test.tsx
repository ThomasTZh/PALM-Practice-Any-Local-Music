/**
 * Component tests for the portable project open panel (M2.16, spec §18.1).
 *
 * The panel is the clean-install entry point: pick or drop a
 * `.basseparate` file, stream it with progress, show the server-side
 * "Opening…" phase, surface inline errors, and hand the new project id
 * to the caller on success.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { cancelOpenSession, uploadArchive, type OpenedProject } from '../src/api/open'
import { OpenProjectPanel } from '../src/projects/OpenProjectPanel'

vi.mock('../src/api/open', () => ({
  uploadArchive: vi.fn(),
  cancelOpenSession: vi.fn(),
  describeOpenError: (error: unknown) => (error instanceof Error ? error.message : String(error)),
}))

const PROJECT_ID = '33333333-3333-4333-8333-333333333333'
const SESSION_ID = '22222222-2222-4222-8222-222222222222'

const opened: OpenedProject = {
  projectId: PROJECT_ID,
  name: 'Song A',
  status: 'ready',
  revision: 5,
}

function setup() {
  const onOpened = vi.fn()
  const view = render(<OpenProjectPanel onOpened={onOpened} />)
  return { onOpened, ...view }
}

function archiveFile(name = 'song.basseparate', bytes = [1, 2, 3]) {
  return new File([new Uint8Array(bytes)], name)
}

function chooseFile(container: HTMLElement, file: File) {
  const input = container.querySelector('input[type="file"]')
  expect(input).not.toBeNull()
  fireEvent.change(input as HTMLInputElement, { target: { files: [file] } })
}

describe('OpenProjectPanel (M2.16 §18.1)', () => {
  beforeEach(() => {
    vi.mocked(uploadArchive).mockReset()
    vi.mocked(cancelOpenSession).mockReset()
    vi.mocked(cancelOpenSession).mockResolvedValue(undefined)
  })

  it('offers a .basseparate drop zone and file picker', () => {
    const { container } = setup()
    expect(screen.getByRole('heading', { name: 'Open a portable project' })).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: /Drop a project archive here or click to browse/,
      }),
    ).toBeInTheDocument()
    const input = container.querySelector('input[type="file"]')
    expect(input).toHaveAttribute('accept', '.basseparate')
  })

  it('rejects a non-archive file locally', async () => {
    const { container } = setup()
    chooseFile(container, new File(['x'], 'song.zip'))
    expect(await screen.findByText(/Choose a .basseparate project file/)).toBeInTheDocument()
    expect(uploadArchive).not.toHaveBeenCalled()
  })

  it('opens the project and reports its id on success', async () => {
    vi.mocked(uploadArchive).mockResolvedValue(opened)
    const { container, onOpened } = setup()
    chooseFile(container, archiveFile())
    await waitFor(() => expect(onOpened).toHaveBeenCalledWith(PROJECT_ID))
    expect(uploadArchive).toHaveBeenCalledWith(expect.objectContaining({ file: expect.any(File) }))
  })

  it('shows the opening phase while the server imports', async () => {
    let resolveUpload!: (project: OpenedProject) => void
    vi.mocked(uploadArchive).mockImplementation((options) => {
      options.onSession?.(SESSION_ID)
      options.onProgress?.({ bytesUploaded: 50, totalBytes: 100 })
      options.onOpening?.()
      return new Promise<OpenedProject>((resolve) => {
        resolveUpload = resolve
      })
    })
    const { container, onOpened } = setup()
    chooseFile(container, archiveFile())

    expect(await screen.findByText(/Opening song\.basseparate/)).toBeInTheDocument()
    resolveUpload(opened)
    await waitFor(() => expect(onOpened).toHaveBeenCalledWith(PROJECT_ID))
  })

  it('shows the server error and allows a retry', async () => {
    vi.mocked(uploadArchive).mockRejectedValue(new Error('damaged archive'))
    const { container, onOpened } = setup()
    chooseFile(container, archiveFile())

    expect(await screen.findByText(/damaged archive/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()

    const user = userEvent.setup()
    vi.mocked(uploadArchive).mockResolvedValue(opened)
    // The same panel instance: dismiss the error, then pick the file again.
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    chooseFile(container, archiveFile())
    await waitFor(() => expect(onOpened).toHaveBeenCalledWith(PROJECT_ID))
  })

  it('cancels the transfer and tells the server', async () => {
    vi.mocked(uploadArchive).mockImplementation((options) => {
      options.onSession?.(SESSION_ID)
      options.onProgress?.({ bytesUploaded: 1, totalBytes: 10 })
      return new Promise<OpenedProject>((_, reject) => {
        options.signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        )
      })
    })
    const { container } = setup()
    chooseFile(container, archiveFile())

    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(cancelOpenSession).toHaveBeenCalledWith(SESSION_ID))
    expect(
      await screen.findByRole('button', {
        name: /Drop a project archive here or click to browse/,
      }),
    ).toBeInTheDocument()
  })

  it('accepts a dragged archive', async () => {
    vi.mocked(uploadArchive).mockResolvedValue(opened)
    const { onOpened } = setup()
    const zone = screen.getByRole('button', {
      name: /Drop a project archive here or click to browse/,
    })
    fireEvent.drop(zone, { dataTransfer: { files: [archiveFile()] } })
    await waitFor(() => expect(onOpened).toHaveBeenCalledWith(PROJECT_ID))
  })
})
