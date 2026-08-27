package com.naixuezhang.studio.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.TextView;

public class SettingsActivity extends Activity {
    private TokenStore tokens;
    private TextView tokenState;
    private EditText tokenInput;
    private TextView deepseekState;
    private EditText deepseekInput;
    private EditText proxyInput;
    private CheckBox onlineProxyBox;
    private CheckBox naiProxyBox;
    private TextView setStatus;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);
        tokens = new TokenStore(this);
        tokenState = findViewById(R.id.tokenState);
        tokenInput = findViewById(R.id.tokenInput);
        deepseekState = findViewById(R.id.deepseekState);
        deepseekInput = findViewById(R.id.deepseekInput);
        proxyInput = findViewById(R.id.proxyInput);
        onlineProxyBox = findViewById(R.id.onlineProxyBox);
        naiProxyBox = findViewById(R.id.naiProxyBox);
        setStatus = findViewById(R.id.setStatus);
        findViewById(R.id.backBtn).setOnClickListener(v -> finish());
        findViewById(R.id.saveBtn).setOnClickListener(v -> confirmSaveNai());
        findViewById(R.id.clearBtn).setOnClickListener(v -> confirmClearNai());
        findViewById(R.id.saveDeepseekBtn).setOnClickListener(v -> confirmSaveDeepseek());
        findViewById(R.id.clearDeepseekBtn).setOnClickListener(v -> confirmClearDeepseek());
        findViewById(R.id.saveNetworkBtn).setOnClickListener(v -> saveNetwork());
        findViewById(R.id.probeOnlineBtn).setOnClickListener(v -> probeOnline());
        findViewById(R.id.verifyOnlineBtn).setOnClickListener(v -> {
            BrowserSession session = BrowserSession.get();
            if (session == null) {
                BrowserSession.attach(this, (android.view.ViewGroup) findViewById(android.R.id.content));
                session = BrowserSession.get();
            }
            if (session != null) session.showVerify(this);
            else setStatus.setText("页面还没准备好，先回到发现再试一次。");
        });
        refreshState();
    }

    private void refreshState() {
        int slots = tokens.count();
        boolean hasNai = slots > 0;
        boolean hasDs = tokens.hasDeepSeek();
        tokenState.setText(hasNai
            ? ("当前：已配置 " + slots + " 个 Token，可 " + slots + " 路并发")
            : "当前：还没填 NovelAI Token");
        tokenState.setTextColor(hasNai ? 0xFF3DDC97 : 0xFFFF7A90);
        deepseekState.setText(hasDs ? "当前：已配置 DeepSeek" : "当前：还没填 DeepSeek");
        deepseekState.setTextColor(hasDs ? 0xFF3DDC97 : 0xFFFF7A90);
        proxyInput.setText(tokens.getProxy());
        onlineProxyBox.setChecked(tokens.onlineUseProxy());
        naiProxyBox.setChecked(tokens.naiUseProxy());
    }

    private void saveNetwork() {
        try {
            tokens.setNetwork(
                String.valueOf(proxyInput.getText()).trim(),
                onlineProxyBox.isChecked(),
                naiProxyBox.isChecked()
            );
            setStatus.setText("网络设置已保存。搜图走代理，出图默认直连。");
            BrowserSession session = BrowserSession.get();
            if (session != null) session.syncProxy(this);
        } catch (Exception error) {
            setStatus.setText(error.getMessage() == null ? "代理格式不对" : error.getMessage());
        }
    }

    private void probeOnline() {
        setStatus.setText("正在测在线库…");
        final int port = getApplication() instanceof StudioApp ? ((StudioApp) getApplication()).getPort() : 18797;
        new Thread(() -> {
            String message = "在线库暂时打不开";
            try {
                java.net.URL url = new java.net.URL("http://127.0.0.1:" + port + "/api/nai/aitag/probe");
                java.net.HttpURLConnection conn = (java.net.HttpURLConnection) url.openConnection(java.net.Proxy.NO_PROXY);
                conn.setConnectTimeout(8000);
                conn.setReadTimeout(50000);
                conn.setRequestMethod("GET");
                java.io.InputStream in = conn.getResponseCode() >= 400 ? conn.getErrorStream() : conn.getInputStream();
                java.io.ByteArrayOutputStream out = new java.io.ByteArrayOutputStream();
                byte[] buf = new byte[2048];
                int n;
                while (in != null && (n = in.read(buf)) >= 0) out.write(buf, 0, n);
                conn.disconnect();
                org.json.JSONObject json = JsonUtil.obj(new String(out.toByteArray(), java.nio.charset.StandardCharsets.UTF_8));
                message = json.optString("message", message);
                String detected = json.optString("detected_proxy", "");
                if (!detected.isEmpty()) message += "  已发现 " + detected;
            } catch (Exception error) {
                message = error.getMessage() == null ? "测不通" : error.getMessage();
            }
            final String text = message;
            runOnUiThread(() -> setStatus.setText(text));
        }).start();
    }

    private void confirmSaveNai() {
        String raw = String.valueOf(tokenInput.getText()).trim();
        if (raw.isEmpty()) {
            setStatus.setText("先粘贴 NovelAI Token");
            return;
        }
        new AlertDialog.Builder(this)
            .setTitle("保存 NovelAI Token")
            .setMessage("每行一个 Token。几个就能并发几路。只写进本机应用存储，不连电脑。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认", (d, w) -> {
                tokens.set(raw);
                tokenInput.setText("");
                setStatus.setText("NovelAI Token 已保存");
                refreshState();
            })
            .show();
    }

    private void confirmClearNai() {
        new AlertDialog.Builder(this)
            .setTitle("清除 NovelAI Token")
            .setMessage("清除后必须重新粘贴才能出图。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认", (d, w) -> {
                tokens.clear();
                tokenInput.setText("");
                setStatus.setText("已清除 NovelAI Token");
                refreshState();
            })
            .show();
    }

    private void confirmSaveDeepseek() {
        String raw = String.valueOf(deepseekInput.getText()).trim();
        if (raw.isEmpty()) {
            setStatus.setText("先粘贴 DeepSeek API Key");
            return;
        }
        new AlertDialog.Builder(this)
            .setTitle("保存 DeepSeek Key")
            .setMessage("只写进本机应用存储。用来写角色槽和优化咒语，不遥控电脑。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认", (d, w) -> {
                tokens.setDeepSeek(raw);
                deepseekInput.setText("");
                setStatus.setText("DeepSeek 已保存");
                refreshState();
            })
            .show();
    }

    private void confirmClearDeepseek() {
        new AlertDialog.Builder(this)
            .setTitle("清除 DeepSeek Key")
            .setMessage("清除后不能再用自然语言写角色或智能优化。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认", (d, w) -> {
                tokens.clearDeepSeek();
                deepseekInput.setText("");
                setStatus.setText("已清除 DeepSeek");
                refreshState();
            })
            .show();
    }
}
