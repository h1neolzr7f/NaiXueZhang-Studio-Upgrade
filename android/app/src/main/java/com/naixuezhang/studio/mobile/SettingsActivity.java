package com.naixuezhang.studio.mobile;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Bundle;
import android.widget.EditText;
import android.widget.TextView;

public class SettingsActivity extends Activity {
    private TokenStore tokens;
    private TextView tokenState;
    private EditText tokenInput;
    private TextView setStatus;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);
        tokens = new TokenStore(this);
        tokenState = findViewById(R.id.tokenState);
        tokenInput = findViewById(R.id.tokenInput);
        setStatus = findViewById(R.id.setStatus);
        findViewById(R.id.backBtn).setOnClickListener(v -> finish());
        findViewById(R.id.saveBtn).setOnClickListener(v -> confirmSave());
        findViewById(R.id.clearBtn).setOnClickListener(v -> confirmClear());
        refreshState();
    }

    private void refreshState() {
        boolean has = tokens.hasToken();
        tokenState.setText(has ? "当前：已配置 Token" : "当前：还没填 Token");
        tokenState.setTextColor(has ? 0xFF3DDC97 : 0xFFFF7A90);
    }

    private void confirmSave() {
        String raw = String.valueOf(tokenInput.getText()).trim();
        if (raw.isEmpty()) {
            setStatus.setText("先粘贴 Token");
            return;
        }
        new AlertDialog.Builder(this)
            .setTitle("保存 Token")
            .setMessage("只写进本机应用存储，不会上传到电脑。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认", (d, w) -> {
                tokens.set(raw);
                tokenInput.setText("");
                setStatus.setText("已保存");
                refreshState();
            })
            .show();
    }

    private void confirmClear() {
        new AlertDialog.Builder(this)
            .setTitle("清除 Token")
            .setMessage("清除后必须重新粘贴才能出图。")
            .setNegativeButton("取消", null)
            .setPositiveButton("确认", (d, w) -> {
                tokens.clear();
                tokenInput.setText("");
                setStatus.setText("已清除");
                refreshState();
            })
            .show();
    }
}
