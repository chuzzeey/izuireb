import { readFile } from "node:fs/promises";
import { join } from "node:path";
import type { Metadata } from "next";
import { getCapturedPage } from "../captured-pages";
import SnapshotFrame from "../snapshot-frame";
import SiteHeader from "../site-header";

export const instant = false;

type LocalPageProps = {
  params: Promise<{ slug: string[] }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
};

function getPageTitle(slug: string[]) {
  return (slug.at(-1) ?? "Page")
    .replace(/[-_]+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export async function generateMetadata({
  params,
  searchParams,
}: LocalPageProps): Promise<Metadata> {
  const { slug } = await params;
  const capturedPage = await getCapturedPage(
    `/${slug.join("/")}`,
    await searchParams,
  );
  return { title: capturedPage?.title ?? getPageTitle(slug) };
}

export default async function LocalPage({
  params,
  searchParams,
}: LocalPageProps) {
  const { slug } = await params;
  const pageTitle = getPageTitle(slug);
  const capturedPage = await getCapturedPage(
    `/${slug.join("/")}`,
    await searchParams,
  );
  if (capturedPage) {
    return (
      <SnapshotFrame src={capturedPage.file} title={capturedPage.title} />
    );
  }

  const snapshot = await readFile(
    join(process.cwd(), "public", "snapshot-content.html"),
    "utf8",
  );
  const header = snapshot.match(
    /<div class="bg-terracotta text-white">[\s\S]*?<\/nav>/,
  );
  if (!header) {
    throw new Error("Could not find the captured site header in snapshot-content.html");
  }
  const headerMarkup = header[0]
    .replaceAll("https://www.hotcshop.com", "")
    .replaceAll("./assets/", "/assets/");

  return (
    <div className="min-h-screen bg-white text-ink antialiased">
      <SiteHeader markup={headerMarkup} />
      <main className="mx-auto max-w-7xl px-4 py-10 sm:py-14">
        <h1 className="text-2xl font-extrabold tracking-tight sm:text-3xl">
          {pageTitle}
        </h1>
        <p className="mt-3 max-w-2xl text-sm text-ink/70 sm:text-base">
          This page was not included in the downloaded homepage. Its original
          content is not available in this local copy.
        </p>
      </main>
    </div>
  );
}
