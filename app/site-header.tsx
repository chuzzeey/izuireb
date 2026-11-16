"use client";

import { useEffect } from "react";

type SiteHeaderProps = {
  markup: string;
};

export default function SiteHeader({ markup }: SiteHeaderProps) {
  useEffect(() => {
    const toggle = document.querySelector<HTMLElement>(
      "[data-mobile-search-toggle]",
    );
    const panel = document.querySelector<HTMLElement>(
      "[data-mobile-search-panel]",
    );
    if (!toggle || !panel) return;

    const onToggle = () => {
      const open = panel.classList.toggle("hidden") === false;
      toggle.setAttribute("aria-expanded", String(open));
      if (open) panel.querySelector<HTMLInputElement>("input[type=search]")?.focus();
    };

    toggle.addEventListener("click", onToggle);
    return () => toggle.removeEventListener("click", onToggle);
  }, []);

  return <div dangerouslySetInnerHTML={{ __html: markup }} />;
}