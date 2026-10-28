import type { Frame, JSHandle } from 'playwright-core';

// One application-created identity is allowed after a verified Send from an empty surface.
export function receiptBoundary(initial: string | null) {
  let identity = initial;
  let armed = false;
  let committed = false;
  let failure: Error | undefined;
  const pending: (string | null)[] = [];
  const invalidate = (message: string) => { failure ??= new Error(message); };
  const advance = (next: string | null) => {
    if (next === identity) return;
    if (committed && identity === null && next !== null) identity = next;
    else invalidate('Conversation changed outside the single post-Send creation transition.');
  };
  return {
    invalidate,
    arm() { armed = true; },
    observe(next: string | null) {
      if (armed && !committed) pending.push(next);
      else advance(next);
    },
    commit() {
      committed = true;
      for (const next of pending) advance(next);
      pending.length = 0;
    },
    check() { if (failure) throw failure; },
  };
}

export type ReceiptInteraction = {
  document: Document;
  interacted: boolean;
  disposed: boolean;
  dispose: () => void;
};

export type ReceiptGuard = {
  interaction: JSHandle<ReceiptInteraction>;
  arm: () => void;
  commit: () => void;
  check: () => Promise<void>;
  dispose: () => Promise<void>;
};

export async function watchReceipt(frame: Frame, initialUrl: string, identify: (url: string) => string | null): Promise<ReceiptGuard> {
  const boundary = receiptBoundary(identify(initialUrl));
  const page = frame.page();
  const observe = (changed: Frame) => {
    if (changed !== frame) return;
    try { boundary.observe(identify(changed.url())); }
    catch { boundary.invalidate('The working frame left the supported conversation route.'); }
  };
  const detached = (changed: Frame) => {
    if (changed === frame) boundary.invalidate('The working conversation frame detached.');
  };
  page.on('framenavigated', observe);
  page.on('framedetached', detached);
  let interaction: JSHandle<ReceiptInteraction> | undefined;
  try {
    interaction = await frame.evaluateHandle(() => {
      const state: ReceiptInteraction = {
        document, interacted: false, disposed: false,
        dispose() {
          state.disposed = true;
          document.removeEventListener('pointerdown', record, true);
          document.removeEventListener('keydown', record, true);
        },
      };
      const record = (event: Event) => { if (event.isTrusted) state.interacted = true; };
      document.addEventListener('pointerdown', record, true);
      document.addEventListener('keydown', record, true);
      return state;
    });
    observe(frame);
    boundary.check();
  } catch (error) {
    page.off('framenavigated', observe);
    page.off('framedetached', detached);
    await interaction?.evaluate(state => state.dispose()).catch(() => undefined);
    await interaction?.dispose().catch(() => undefined);
    throw error;
  }
  return {
    interaction,
    arm: boundary.arm,
    commit: boundary.commit,
    async check() {
      observe(frame);
      boundary.check();
      const intact = await interaction.evaluate(state => state.document === document && !state.interacted && !state.disposed);
      if (!intact) boundary.invalidate('Human interaction or document replacement invalidated the response proof.');
      boundary.check();
    },
    async dispose() {
      page.off('framenavigated', observe);
      page.off('framedetached', detached);
      await interaction.evaluate(state => state.dispose()).catch(() => undefined);
      await interaction.dispose().catch(() => undefined);
    },
  };
}
