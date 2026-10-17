/** Reveal the requested receipt even when it is inside a folded episode. */
export function revealNewsArticle(element: HTMLElement, behavior: ScrollBehavior = 'auto') {
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (parent instanceof HTMLDetailsElement) parent.open = true;
  }
  element.scrollIntoView({ behavior, block: 'start' });
}
