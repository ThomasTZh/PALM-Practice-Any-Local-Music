/** Vite `?raw` imports: the worklet sources are concatenated into a Blob. */
declare module "*?raw" {
  const source: string;
  export default source;
}
