package com.signage.watchdog;

import android.content.Intent;
import android.os.Bundle;
import android.util.Log;
import androidx.appcompat.app.AppCompatActivity;

/**
 * Transparent trampoline that launches the signage player.
 * Used when we're in foreground (e.g. user opened app) and can legally start activities.
 */
public class LaunchTrampolineActivity extends AppCompatActivity {
    private static final String TAG = "SignageWatchdog";

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        launchPlayer();
        finish();
    }

    private void launchPlayer() {
        String target = WatchdogService.TARGET_PACKAGE;
        try {
            Intent launchIntent = getPackageManager().getLaunchIntentForPackage(target);
            if (launchIntent == null) {
                launchIntent = new Intent(Intent.ACTION_MAIN);
                launchIntent.setClassName(target, target + ".MainActivity");
            }
            launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP
                | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED | Intent.FLAG_ACTIVITY_SINGLE_TOP
                | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT);
            startActivity(launchIntent);
            Log.i(TAG, "Trampoline launched: " + target);
        } catch (Exception e) {
            Log.e(TAG, "Trampoline failed to launch player", e);
        }
    }
}
