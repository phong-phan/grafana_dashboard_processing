(() => {
  "use strict";

  const state = {
    files: [],           // [{name, content}]
    config: null,        // {site: {current, replace_with}, datasources: [...], hosts: [...]}
    pendingImport: null,  // config-shaped object loaded via "Import config.json", applied on next scan
  };

  const el = (id) => document.getElementById(id);

  const dropzone = el("dropzone");
  const fileInput = el("file-input");
  const fileListEl = el("file-list");
  const warningsEl = el("scan-warnings");
  const configInput = el("config-input");

  const editorSection = el("editor-section");
  const applySection = el("apply-section");

  const siteRow = el("site-row");
  const dsRows = el("datasource-rows");
  const dsEmpty = el("datasource-empty");
  const hostRows = el("host-rows");
  const hostEmpty = el("host-empty");
  const addHostBtn = el("add-host-btn");
  const transformRows = el("transformation-rows");
  const transformEmpty = el("transformation-empty");
  const valueMappingRows = el("value-mapping-rows");
  const valueMappingEmpty = el("value-mapping-empty");
  const urlRows = el("url-rows");
  const urlEmpty = el("url-empty");
  const panelTitleRows = el("panel-title-rows");
  const panelTitleEmpty = el("panel-title-empty");
  const textContentRows = el("text-content-rows");
  const textContentEmpty = el("text-content-empty");

  const downloadConfigBtn = el("download-config-btn");
  const applyBtn = el("apply-btn");
  const applyStatus = el("apply-status");

  // ---------- File loading ----------

  function readFileAsText(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(reader.error);
      reader.readAsText(file);
    });
  }

  async function addFiles(fileList) {
    const jsonFiles = Array.from(fileList).filter((f) => f.name.endsWith(".json"));
    for (const file of jsonFiles) {
      const content = await readFileAsText(file);
      const existingIdx = state.files.findIndex((f) => f.name === file.name);
      if (existingIdx >= 0) {
        state.files[existingIdx] = { name: file.name, content };
      } else {
        state.files.push({ name: file.name, content });
      }
    }
    renderFileList();
    if (state.files.length > 0) {
      await scanFiles();
    } else {
      editorSection.classList.add("hidden");
      applySection.classList.add("hidden");
    }
  }

  function removeFile(name) {
    state.files = state.files.filter((f) => f.name !== name);
    renderFileList();
    if (state.files.length > 0) {
      scanFiles();
    } else {
      state.config = null;
      editorSection.classList.add("hidden");
      applySection.classList.add("hidden");
    }
  }

  function renderFileList() {
    fileListEl.innerHTML = "";
    state.files.forEach((f) => {
      const row = document.createElement("div");
      row.className = "file-item";
      const name = document.createElement("span");
      name.className = "fname";
      name.textContent = f.name;
      const remove = document.createElement("button");
      remove.className = "remove-file";
      remove.type = "button";
      remove.textContent = "Remove";
      remove.addEventListener("click", () => removeFile(f.name));
      row.appendChild(name);
      row.appendChild(remove);
      fileListEl.appendChild(row);
    });
  }

  dropzone.addEventListener("click", (e) => {
    if (e.target !== fileInput) fileInput.click();
  });
  fileInput.addEventListener("change", (e) => addFiles(e.target.files));

  ["dragenter", "dragover"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.add("drag-over");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropzone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropzone.classList.remove("drag-over");
    })
  );
  dropzone.addEventListener("drop", (e) => {
    if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });

  // ---------- Scan ----------

  async function scanFiles() {
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ files: state.files }),
    });
    const data = await res.json();

    if (!res.ok) {
      warningsEl.classList.remove("hidden");
      warningsEl.textContent = data.error || "Failed to scan files.";
      return;
    }

    if (data.warnings && data.warnings.length) {
      warningsEl.classList.remove("hidden");
      warningsEl.textContent = data.warnings.join(" ");
    } else {
      warningsEl.classList.add("hidden");
    }

    rebuildConfigFromScan(data);
    editorSection.classList.remove("hidden");
    applySection.classList.remove("hidden");
    renderAll();
  }

  function rebuildConfigFromScan(scanResult) {
    const prev = state.pendingImport || state.config;
    state.pendingImport = null;

    // Site
    const detectedSite = scanResult.sites[0] || "";
    let siteReplace = detectedSite;
    if (prev && prev.site && prev.site.current === detectedSite) {
      siteReplace = prev.site.replace_with;
    } else if (state.pendingImportUsed) {
      siteReplace = prev.site.replace_with;
    }
    const site = { current: detectedSite, replace_with: siteReplace };

    // Datasources
    const prevDsMap = {};
    if (prev && prev.datasources) {
      prev.datasources.forEach((d) => {
        prevDsMap[d.type + "|" + d.uid.current] = d.uid.replace_with;
      });
    }
    const datasources = scanResult.datasources.map((d) => {
      const key = d.type + "|" + d.uid;
      const replace = prevDsMap.hasOwnProperty(key) ? prevDsMap[key] : d.uid;
      return { type: d.type, uid: { current: d.uid, replace_with: replace } };
    });

    // Hosts: keep prior edits for hosts still detected, keep manually-added
    // "new host" rows (current === null), add newly detected hosts unchanged.
    const prevHostMap = {};
    const extraHostRows = [];
    if (prev && prev.hosts) {
      prev.hosts.forEach((h) => {
        if (h.current) {
          prevHostMap[h.current] = h.replace_with;
        } else {
          extraHostRows.push({ current: null, replace_with: h.replace_with });
        }
      });
    }
    const hosts = scanResult.hosts
      .map((h) => ({
        current: h,
        replace_with: prevHostMap.hasOwnProperty(h) ? prevHostMap[h] : h,
      }))
      .concat(extraHostRows);

    // Transformations ("Rename fields by regex"): keyed by the current
    // regex+renamePattern pair, same dedup-and-edit-once approach as datasources.
    const prevTransformMap = {};
    if (prev && prev.transformations) {
      prev.transformations.forEach((t) => {
        const key = (t.current.regex || "") + "::" + (t.current.renamePattern || "");
        prevTransformMap[key] = t.replace_with;
      });
    }
    const transformations = (scanResult.transformations || []).map((t) => {
      const key = (t.regex || "") + "::" + (t.renamePattern || "");
      const replace = prevTransformMap.hasOwnProperty(key)
        ? prevTransformMap[key]
        : { regex: t.regex, renamePattern: t.renamePattern };
      return { current: { regex: t.regex, renamePattern: t.renamePattern }, replace_with: replace };
    });

    // Value mappings: keyed by the current value+text pair, same
    // dedup-and-edit-once approach as transformations.
    const prevValueMappingMap = {};
    if (prev && prev.value_mappings) {
      prev.value_mappings.forEach((vm) => {
        const key = (vm.current.value || "") + "::" + (vm.current.text || "");
        prevValueMappingMap[key] = vm.replace_with;
      });
    }
    const valueMappings = (scanResult.value_mappings || []).map((vm) => {
      const key = (vm.value || "") + "::" + (vm.text || "");
      const replace = prevValueMappingMap.hasOwnProperty(key)
        ? prevValueMappingMap[key]
        : { value: vm.value, text: vm.text };
      return { current: { value: vm.value, text: vm.text }, replace_with: replace };
    });

    // Data pull URLs: flat current -> replace_with, same as datasource UIDs.
    const prevUrlMap = {};
    if (prev && prev.urls) {
      prev.urls.forEach((u) => {
        prevUrlMap[u.current] = u.replace_with;
      });
    }
    const urls = (scanResult.urls || []).map((u) => ({
      current: u,
      replace_with: prevUrlMap.hasOwnProperty(u) ? prevUrlMap[u] : u,
    }));

    // Panel titles: flat current -> replace_with.
    const prevPanelTitleMap = {};
    if (prev && prev.panel_titles) {
      prev.panel_titles.forEach((t) => {
        prevPanelTitleMap[t.current] = t.replace_with;
      });
    }
    const panelTitles = (scanResult.panel_titles || []).map((t) => ({
      current: t,
      replace_with: prevPanelTitleMap.hasOwnProperty(t) ? prevPanelTitleMap[t] : t,
    }));

    // Text panel content: flat current -> replace_with.
    const prevTextContentMap = {};
    if (prev && prev.text_content) {
      prev.text_content.forEach((c) => {
        prevTextContentMap[c.current] = c.replace_with;
      });
    }
    const textContent = (scanResult.text_content || []).map((c) => ({
      current: c,
      replace_with: prevTextContentMap.hasOwnProperty(c) ? prevTextContentMap[c] : c,
    }));

    state.config = {
      site,
      datasources,
      hosts,
      transformations,
      value_mappings: valueMappings,
      urls,
      panel_titles: panelTitles,
      text_content: textContent,
    };
  }

  // ---------- Import config.json ----------

  configInput.addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const text = await readFileAsText(file);
      const parsed = JSON.parse(text);
      const imported = {
        site: parsed.site_name || { current: "", replace_with: "" },
        datasources: parsed.datasources || [],
        hosts: parsed.hosts || [],
        transformations: parsed.transformations || [],
        value_mappings: parsed.value_mappings || [],
        urls: parsed.urls || [],
        panel_titles: parsed.panel_titles || [],
        text_content: parsed.text_content || [],
      };
      if (state.config) {
        state.pendingImport = imported;
        rebuildConfigFromScan({
          sites: [state.config.site.current].filter(Boolean),
          datasources: state.config.datasources.map((d) => ({ type: d.type, uid: d.uid.current })),
          hosts: state.config.hosts.filter((h) => h.current).map((h) => h.current),
          transformations: state.config.transformations.map((t) => t.current),
          value_mappings: state.config.value_mappings.map((vm) => vm.current),
          urls: state.config.urls.map((u) => u.current),
          panel_titles: state.config.panel_titles.map((t) => t.current),
          text_content: state.config.text_content.map((c) => c.current),
        });
        renderAll();
      } else {
        state.pendingImport = imported;
      }
    } catch (err) {
      alert("Could not read config.json: " + err.message);
    }
    configInput.value = "";
  });

  // ---------- Rendering ----------

  function renderAll() {
    renderSite();
    renderDatasources();
    renderHosts();
    renderTransformations();
    renderValueMappings();
    renderUrls();
    renderPanelTitles();
    renderTextContent();
  }

  function renderSite() {
    siteRow.innerHTML = "";
    const row = document.createElement("div");
    row.className = "table-row two-col";

    const current = document.createElement("div");
    current.className = "current-value";
    current.textContent = state.config.site.current || "(no site detected)";

    const inputWrap = document.createElement("div");
    const input = document.createElement("input");
    input.type = "text";
    input.value = state.config.site.replace_with || "";
    input.addEventListener("input", () => {
      state.config.site.replace_with = input.value;
    });
    inputWrap.appendChild(input);

    row.appendChild(current);
    row.appendChild(inputWrap);
    siteRow.appendChild(row);
  }

  function renderDatasources() {
    dsRows.innerHTML = "";
    dsEmpty.classList.toggle("hidden", state.config.datasources.length > 0);

    state.config.datasources.forEach((ds, idx) => {
      const row = document.createElement("div");
      row.className = "table-row two-col";

      const current = document.createElement("div");
      current.className = "current-value";
      const typeLabel = document.createElement("span");
      typeLabel.className = "ds-type";
      typeLabel.textContent = ds.type;
      current.appendChild(typeLabel);
      current.appendChild(document.createTextNode(ds.uid.current));

      const inputWrap = document.createElement("div");
      const input = document.createElement("input");
      input.type = "text";
      input.value = ds.uid.replace_with;
      input.addEventListener("input", () => {
        state.config.datasources[idx].uid.replace_with = input.value;
      });
      inputWrap.appendChild(input);

      row.appendChild(current);
      row.appendChild(inputWrap);
      dsRows.appendChild(row);
    });
  }

  function renderTransformations() {
    transformRows.innerHTML = "";
    const transformations = state.config.transformations || [];
    transformEmpty.classList.toggle("hidden", transformations.length > 0);

    transformations.forEach((t, idx) => {
      const row = document.createElement("div");
      row.className = "table-row two-col";

      const current = document.createElement("div");
      current.className = "current-value";

      const matchField = document.createElement("span");
      matchField.className = "transform-field";
      const matchLabel = document.createElement("span");
      matchLabel.className = "field-label";
      matchLabel.textContent = "Match";
      matchField.appendChild(matchLabel);
      matchField.appendChild(document.createTextNode(t.current.regex || ""));
      current.appendChild(matchField);

      const replaceField = document.createElement("span");
      replaceField.className = "transform-field";
      const replaceLabel = document.createElement("span");
      replaceLabel.className = "field-label";
      replaceLabel.textContent = "Replace";
      replaceField.appendChild(replaceLabel);
      replaceField.appendChild(document.createTextNode(t.current.renamePattern || ""));
      current.appendChild(replaceField);

      const inputsWrap = document.createElement("div");
      inputsWrap.className = "transform-inputs";

      const regexInput = document.createElement("input");
      regexInput.type = "text";
      regexInput.placeholder = "Match (regex)";
      regexInput.value = t.replace_with.regex || "";
      regexInput.addEventListener("input", () => {
        state.config.transformations[idx].replace_with.regex = regexInput.value;
      });

      const renameInput = document.createElement("input");
      renameInput.type = "text";
      renameInput.placeholder = "Replace";
      renameInput.value = t.replace_with.renamePattern || "";
      renameInput.addEventListener("input", () => {
        state.config.transformations[idx].replace_with.renamePattern = renameInput.value;
      });

      inputsWrap.appendChild(regexInput);
      inputsWrap.appendChild(renameInput);

      row.appendChild(current);
      row.appendChild(inputsWrap);
      transformRows.appendChild(row);
    });
  }

  function renderValueMappings() {
    valueMappingRows.innerHTML = "";
    const valueMappings = state.config.value_mappings || [];
    valueMappingEmpty.classList.toggle("hidden", valueMappings.length > 0);

    valueMappings.forEach((vm, idx) => {
      const row = document.createElement("div");
      row.className = "table-row two-col";

      const current = document.createElement("div");
      current.className = "current-value";

      const valueField = document.createElement("span");
      valueField.className = "transform-field";
      const valueLabel = document.createElement("span");
      valueLabel.className = "field-label";
      valueLabel.textContent = "Value";
      valueField.appendChild(valueLabel);
      valueField.appendChild(document.createTextNode(vm.current.value ?? ""));
      current.appendChild(valueField);

      const textField = document.createElement("span");
      textField.className = "transform-field";
      const textLabel = document.createElement("span");
      textLabel.className = "field-label";
      textLabel.textContent = "Display text";
      textField.appendChild(textLabel);
      textField.appendChild(document.createTextNode(vm.current.text || ""));
      current.appendChild(textField);

      const inputsWrap = document.createElement("div");
      inputsWrap.className = "transform-inputs";

      const valueInput = document.createElement("input");
      valueInput.type = "text";
      valueInput.placeholder = "Value";
      valueInput.value = vm.replace_with.value ?? "";
      valueInput.addEventListener("input", () => {
        state.config.value_mappings[idx].replace_with.value = valueInput.value;
      });

      const textInput = document.createElement("input");
      textInput.type = "text";
      textInput.placeholder = "Display text";
      textInput.value = vm.replace_with.text || "";
      textInput.addEventListener("input", () => {
        state.config.value_mappings[idx].replace_with.text = textInput.value;
      });

      inputsWrap.appendChild(valueInput);
      inputsWrap.appendChild(textInput);

      row.appendChild(current);
      row.appendChild(inputsWrap);
      valueMappingRows.appendChild(row);
    });
  }

  function renderUrls() {
    urlRows.innerHTML = "";
    const urls = state.config.urls || [];
    urlEmpty.classList.toggle("hidden", urls.length > 0);

    urls.forEach((u, idx) => {
      const row = document.createElement("div");
      row.className = "table-row two-col";

      const current = document.createElement("div");
      current.className = "current-value";
      current.textContent = u.current;

      const inputWrap = document.createElement("div");
      const input = document.createElement("input");
      input.type = "text";
      input.value = u.replace_with;
      input.addEventListener("input", () => {
        state.config.urls[idx].replace_with = input.value;
      });
      inputWrap.appendChild(input);

      row.appendChild(current);
      row.appendChild(inputWrap);
      urlRows.appendChild(row);
    });
  }

  function renderPanelTitles() {
    panelTitleRows.innerHTML = "";
    const panelTitles = state.config.panel_titles || [];
    panelTitleEmpty.classList.toggle("hidden", panelTitles.length > 0);

    panelTitles.forEach((t, idx) => {
      const row = document.createElement("div");
      row.className = "table-row two-col";

      const current = document.createElement("div");
      current.className = "current-value";
      current.textContent = t.current;

      const inputWrap = document.createElement("div");
      const input = document.createElement("input");
      input.type = "text";
      input.value = t.replace_with;
      input.addEventListener("input", () => {
        state.config.panel_titles[idx].replace_with = input.value;
      });
      inputWrap.appendChild(input);

      row.appendChild(current);
      row.appendChild(inputWrap);
      panelTitleRows.appendChild(row);
    });
  }

  function renderTextContent() {
    textContentRows.innerHTML = "";
    const textContent = state.config.text_content || [];
    textContentEmpty.classList.toggle("hidden", textContent.length > 0);

    textContent.forEach((c, idx) => {
      const row = document.createElement("div");
      row.className = "table-row two-col";

      const current = document.createElement("textarea");
      current.className = "current-value textarea-field";
      current.value = c.current;
      current.readOnly = true;
      current.rows = 3;

      const textarea = document.createElement("textarea");
      textarea.className = "textarea-field";
      textarea.rows = 3;
      textarea.value = c.replace_with;
      textarea.addEventListener("input", () => {
        state.config.text_content[idx].replace_with = textarea.value;
      });

      row.appendChild(current);
      row.appendChild(textarea);
      textContentRows.appendChild(row);
    });
  }

  function actionForHost(h) {
    if (h.replace_with === "" ) return "remove";
    if (h.replace_with === null) return "nullify";
    return "rename";
  }

  function renderHosts() {
    hostRows.innerHTML = "";
    hostEmpty.classList.toggle("hidden", state.config.hosts.length > 0);

    state.config.hosts.forEach((host, idx) => {
      const row = document.createElement("div");
      row.className = "table-row three-col";

      const current = document.createElement("div");
      current.className = "current-value" + (host.current ? "" : " is-new");
      current.textContent = host.current || "(new host)";
      row.appendChild(current);

      if (host.current === null) {
        // Manually-added extra host: just a target name + delete row button.
        const actionCell = document.createElement("button");
        actionCell.type = "button";
        actionCell.className = "remove-row-btn";
        actionCell.textContent = "Delete row";
        actionCell.addEventListener("click", () => {
          state.config.hosts.splice(idx, 1);
          renderHosts();
        });
        row.appendChild(actionCell);

        const inputWrap = document.createElement("div");
        const input = document.createElement("input");
        input.type = "text";
        input.placeholder = "new-host-name";
        input.value = host.replace_with || "";
        input.addEventListener("input", () => {
          state.config.hosts[idx].replace_with = input.value;
        });
        inputWrap.appendChild(input);
        row.appendChild(inputWrap);
      } else {
        const select = document.createElement("select");
        [
          ["rename", "Rename to"],
          ["remove", "Remove (delete panels)"],
          ["nullify", "Blank out (keep panel)"],
        ].forEach(([value, label]) => {
          const opt = document.createElement("option");
          opt.value = value;
          opt.textContent = label;
          select.appendChild(opt);
        });
        select.value = actionForHost(host);

        const inputWrap = document.createElement("div");
        const input = document.createElement("input");
        input.type = "text";
        input.value = typeof host.replace_with === "string" ? host.replace_with : host.current;
        input.dataset.lastValue = input.value;

        function syncInputState() {
          if (select.value === "rename") {
            input.disabled = false;
            input.value = input.dataset.lastValue || host.current;
            state.config.hosts[idx].replace_with = input.value;
          } else if (select.value === "remove") {
            input.disabled = true;
            state.config.hosts[idx].replace_with = "";
          } else if (select.value === "nullify") {
            input.disabled = true;
            state.config.hosts[idx].replace_with = null;
          }
        }
        syncInputState();

        select.addEventListener("change", syncInputState);
        input.addEventListener("input", () => {
          input.dataset.lastValue = input.value;
          state.config.hosts[idx].replace_with = input.value;
        });

        inputWrap.appendChild(input);
        row.appendChild(select);
        row.appendChild(inputWrap);
      }

      hostRows.appendChild(row);
    });
  }

  addHostBtn.addEventListener("click", () => {
    state.config.hosts.push({ current: null, replace_with: "" });
    renderHosts();
  });

  // ---------- Download config.json ----------

  function buildConfigPayload() {
    return {
      instructions:
        "Map 'current' values to 'replace_with'. To remove a host, leave 'replace_with' as null or empty string.",
      datasources: state.config.datasources,
      site_name: state.config.site,
      hosts: state.config.hosts,
      transformations: state.config.transformations,
      value_mappings: state.config.value_mappings,
      urls: state.config.urls,
      panel_titles: state.config.panel_titles,
      text_content: state.config.text_content,
    };
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  downloadConfigBtn.addEventListener("click", () => {
    if (!state.config) return;
    const blob = new Blob([JSON.stringify(buildConfigPayload(), null, 2)], {
      type: "application/json",
    });
    triggerDownload(blob, "config.json");
  });

  // ---------- Apply ----------

  applyBtn.addEventListener("click", async () => {
    if (!state.config || state.files.length === 0) return;
    applyBtn.disabled = true;
    applyStatus.classList.remove("hidden", "ok", "error");
    applyStatus.textContent = "Applying...";

    try {
      const res = await fetch("/api/apply", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ files: state.files, config: buildConfigPayload() }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Apply failed.");
      }

      const disposition = res.headers.get("Content-Disposition") || "";
      const match = disposition.match(/filename="(.+)"/);
      const filename = match ? match[1] : "customized_dashboard.json";
      const blob = await res.blob();
      triggerDownload(blob, filename);

      applyStatus.classList.add("ok");
      applyStatus.textContent = `Done. Downloaded ${filename}.`;
    } catch (err) {
      applyStatus.classList.add("error");
      applyStatus.textContent = err.message;
    } finally {
      applyBtn.disabled = false;
    }
  });
})();
