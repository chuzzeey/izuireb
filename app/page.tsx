import { getCapturedPage } from "./captured-pages";
import SnapshotFrame from "./snapshot-frame";

export const instant = false;

type HomeProps = {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

export default async function Home({ searchParams }: HomeProps) {
  const capturedPage = await getCapturedPage("/", await searchParams);
  return (
    <SnapshotFrame
      src={capturedPage?.file ?? "/snapshot.html"}
      title={capturedPage?.title ?? "Izuire Shop"}
    />
  );
}
