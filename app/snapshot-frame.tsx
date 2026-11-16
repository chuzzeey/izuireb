type SnapshotFrameProps = {
  src: string;
  title: string;
};

export default function SnapshotFrame({ src, title }: SnapshotFrameProps) {
  return (
    <iframe
      title={title}
      src={src}
      style={{
        position: "fixed",
        inset: 0,
        display: "block",
        width: "100vw",
        height: "100dvh",
        border: 0,
      }}
    />
  );
}
