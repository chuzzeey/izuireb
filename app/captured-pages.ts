import { readFile } from "node:fs/promises";
import { join } from "node:path";

type SearchParams = Record<string, string | string[] | undefined>;

type CapturedPage = {
  file: string;
  title: string;
};

type CaptureManifest = {
  source: string;
  pages: Record<string, CapturedPage>;
};

function isCaptureManifest(value: unknown): value is CaptureManifest {
  if (typeof value !== "object" || value === null || !("pages" in value)) {
    return false;
  }

  const manifest = value as { source?: unknown; pages?: unknown };
  if (
    typeof manifest.source !== "string" ||
    typeof manifest.pages !== "object" ||
    manifest.pages === null
  ) {
    return false;
  }

  return Object.values(manifest.pages).every(
    (page) =>
      typeof page === "object" &&
      page !== null &&
      "file" in page &&
      "title" in page &&
      typeof page.file === "string" &&
      typeof page.title === "string",
  );
}

function routeKey(pathname: string, searchParams: SearchParams) {
  const path = pathname === "/" ? "/" : pathname.replace(/\/+$/, "");
  const entries = Object.entries(searchParams)
    .flatMap(([key, value]) => {
      if (value === undefined) return [];
      return (Array.isArray(value) ? value : [value]).map(
        (item) => [key, item] as const,
      );
    })
    .sort(([keyA, valueA], [keyB, valueB]) =>
      keyA === keyB
        ? valueA.localeCompare(valueB)
        : keyA.localeCompare(keyB),
    );

  const query = new URLSearchParams();
  for (const [key, value] of entries) {
    query.append(key, value);
  }

  const serializedQuery = query.toString();
  return serializedQuery ? `${path}?${serializedQuery}` : path;
}

export async function getCapturedPage(
  pathname: string,
  searchParams: SearchParams = {},
): Promise<CapturedPage | undefined> {
  const manifestPath = join(
    process.cwd(),
    "public",
    "site-capture",
    "manifest.json",
  );
  const contents = await readFile(manifestPath, "utf8");
  const parsed: unknown = JSON.parse(contents);
  if (!isCaptureManifest(parsed)) {
    throw new Error("The downloaded site capture manifest is invalid.");
  }

  return parsed.pages[routeKey(pathname, searchParams)];
}
