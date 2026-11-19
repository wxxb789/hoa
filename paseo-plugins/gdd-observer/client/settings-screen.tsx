import type { PluginSurfaceProps } from "@getpaseo/plugin/client";
import { useSettings, useTranslation } from "@getpaseo/plugin/client";
import {
  SettingsAction,
  SettingsCard,
  SettingsInput,
  SettingsRow,
  SettingsSection,
  SettingsSelect,
  Loading,
  type SettingsInputHandle,
  useToast,
} from "@getpaseo/plugin/client/ui";
import { useQueryClient } from "@tanstack/react-query";
import { useMemo, useRef, useState } from "react";
import { Text } from "react-native";
import { observerSettings, type ObserverSettings } from "../shared/settings";
import { errorText } from "./format";
import { sourceKey } from "./labels";
import { messages } from "./messages";
import { StatusStrip } from "./status-strip";
import { useObserverStyles } from "./styles";
import { RUNS_LIST_QUERY_KEY, useRunsListQuery } from "./use-runs-query";

const POLL_OPTIONS = [1000, 2000, 5000, 15000, 30000];
const TAIL_OPTIONS = [40, 80, 200, 500];
export function ObserverSettingsScreen({ theme, layout }: PluginSurfaceProps) {
  const styles = useObserverStyles(theme, layout);
  const { t } = useTranslation(messages);
  const toast = useToast();
  const settings = useSettings(observerSettings);
  const queryClient = useQueryClient();
  const [draftRevision, setDraftRevision] = useState<string | null>(null);
  const input = useRef<SettingsInputHandle | null>(null);

  // Observes the same scan as the panel and keeps this screen's fixed 10,000 ms request; when the
  // panel asks for a faster cadence the shared election polls at that cadence instead.
  const scan = useRunsListQuery(10_000);

  const values = settings.status === "ready" ? settings.values : null;
  const revision =
    settings.status === "ready" || settings.status === "invalid" ? settings.revision : null;
  const savedRoot = values?.runRoot ?? "";
  const pollOptions = useMemo(
    () =>
      POLL_OPTIONS.map((ms) => ({
        label: t("settingsScreen.pollOption", { seconds: ms / 1000 }),
        value: String(ms),
      })),
    [t],
  );
  const tailOptions = useMemo(
    () =>
      TAIL_OPTIONS.map((lines) => ({
        label: t("settingsScreen.tailOption", { count: lines }),
        value: String(lines),
      })),
    [t],
  );

  async function saveRoot(value: string, against: string | null): Promise<boolean> {
    if (!values || against === null) return false;
    const next = value.trim();
    if (next !== "" && !isAbsolutePath(next)) {
      toast.error(t("settingsScreen.rootError"));
      return false;
    }
    if (next === savedRoot) {
      setDraftRevision(null);
      return true;
    }
    const saved = await settings.save({ ...values, runRoot: next }, against);
    if (saved) {
      toast.show(t("settingsScreen.saved"), { variant: "success" });
      setDraftRevision(null);
      // The scan resolves the run root on every call, so reload the shared observation right away
      // instead of leaving the panel on the previous root until its next polling tick.
      void queryClient.invalidateQueries({ queryKey: RUNS_LIST_QUERY_KEY });
    } else {
      toast.error(settings.saveError ?? t("settingsScreen.saveFailed"));
    }
    return saved;
  }

  async function saveSetting(patch: Partial<ObserverSettings>) {
    if (!values || revision === null) return;
    const saved = await settings.save({ ...values, ...patch }, revision);
    if (!saved) toast.error(settings.saveError ?? t("settingsScreen.saveFailed"));
  }

  if (settings.status !== "ready") {
    if (settings.status === "loading") {
      return <Loading />;
    }
    return (
      <Text style={styles.error}>{t("settingsScreen.invalid", { error: settings.error })}</Text>
    );
  }

  const storedRootMissing = draftRevision === null && scan.data?.rootExists === false;
  return (
    <>
      <SettingsSection title={t("settingsScreen.root")} info={t("settingsScreen.rootHint")}>
        <SettingsCard>
          <SettingsInput
            ref={input}
            label={t("settingsScreen.root")}
            hint={t("settingsScreen.rootHint")}
            error={storedRootMissing ? t("list.missing") : null}
            initialValue={savedRoot}
            onChangeText={() => setDraftRevision(revision)}
          />
          <SettingsAction
            label={t("settingsScreen.save")}
            actionLabel={t("settingsScreen.save")}
            disabled={settings.saving}
            onPress={() => {
              void saveRoot(input.current?.getText() ?? savedRoot, draftRevision ?? revision);
            }}
          />
          <SettingsAction
            label={t("settingsScreen.clear")}
            actionLabel={t("settingsScreen.clear")}
            disabled={settings.saving}
            onPress={() => {
              input.current?.replaceText("");
              setDraftRevision(revision);
              void saveRoot("", revision);
            }}
          />
        </SettingsCard>
      </SettingsSection>
      <SettingsSection title={t("stats.title")}>
        <SettingsCard>
          {scan.data ? (
            <StatusStrip stats={scan.data.stats} theme={theme} layout={layout} />
          ) : (
            <Text style={styles.muted}>{t("list.scanning")}</Text>
          )}
        </SettingsCard>
      </SettingsSection>
      <SettingsSection title={t("settingsScreen.resolved")}>
        <SettingsCard>
          <SettingsRow label={t("settingsScreen.resolved")}>
            <Text style={styles.body} selectable>
              {scan.data?.runRoot ?? t("list.scanning")}
            </Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.resolvedFrom")}>
            <Text style={styles.body}>
              {scan.data ? t(sourceKey(scan.data.rootSource)) : t("list.scanning")}
            </Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.exists")}>
            <Text style={styles.body}>
              {scan.data ? (scan.data.rootExists ? t("settingsScreen.yes") : t("settingsScreen.no")) : "—"}
            </Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.probe")}>
            <Text style={styles.body}>{scan.data?.probe ?? "—"}</Text>
          </SettingsRow>
          <SettingsRow label={t("settingsScreen.candidates")}>
            <Text style={styles.muted} selectable>
              {(scan.data?.candidates ?? [])
                .map(
                  (candidate) =>
                    `${candidate.exists ? "✓" : "·"} ${candidate.path} (${t(sourceKey(candidate.source))})`,
                )
                .join("\n")}
            </Text>
          </SettingsRow>
          {scan.error ? (
            <Text style={styles.error}>{t("error.list", { error: errorText(scan.error) })}</Text>
          ) : null}
        </SettingsCard>
      </SettingsSection>
      <SettingsSection title={t("settingsScreen.poll")}>
        <SettingsCard>
          <SettingsSelect
            label={t("settingsScreen.poll")}
            value={String(settings.values.pollIntervalMs)}
            options={pollOptions}
            disabled={settings.saving}
            onValueChange={(value) => void saveSetting({ pollIntervalMs: Number(value) })}
          />
          <SettingsSelect
            label={t("settingsScreen.tail")}
            value={String(settings.values.tailLines)}
            options={tailOptions}
            disabled={settings.saving}
            onValueChange={(value) => void saveSetting({ tailLines: Number(value) })}
          />
        </SettingsCard>
      </SettingsSection>
    </>
  );
}

function isAbsolutePath(path: string): boolean {
  return /^[A-Za-z]:[\\/]/.test(path) || path.startsWith("/") || path.startsWith("\\\\");
}
