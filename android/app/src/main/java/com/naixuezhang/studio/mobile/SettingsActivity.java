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
        refreshState();
    }

    private void refreshState() {
        boolean hasNai = tokens.hasToken();
        boolean hasDs = tokens.hasDeepSeek();
        tokenState.setText(hasNai ? "当前：已配置 NovelAI Token" : "当前：还没填 NovelAI Token");
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
        } catch (Exception error) {
            setStatus.setText(error.getMessage() == null ? "代理格式不对" : error.getMessage());
        }
    }

    private void confirmSaveNai() {
        String raw = String.valueOf(tokenInput.getText()).trim();
        if (raw.isEmpty()) {
            setStatus.setText("先粘贴 NovelAI Token");
            return;
        }
        new AlertDialog.Builder(this)
            .setTitle("保存 NovelAI Token")
            .setMessage("只写进本机应用存储。不连电脑，出图直接走 NovelAI。")
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
