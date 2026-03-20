// https://claude.ai/share/a604cfdd-afe1-4c74-b37f-f1741b4431ff

#pragma once

#define BTN_U 0b0001
#define BTN_D 0b0010
#define BTN_L 0b0100
#define BTN_R 0b1000

// Given change in params clear screen of old pixels
void vid_crop_update_clear(crop2d_params_t old, crop2d_params_t new) {
    uint32_t scale = mm_regs->scale_params.scale;
    uint32_t fb_x  = mm_regs->fb_pos_params.xpos;
    uint32_t fb_y  = mm_regs->fb_pos_params.ypos;

    uint32_t old_w = (old.bot_right_x - old.top_left_x) * scale;
    uint32_t old_h = (old.bot_right_y - old.top_left_y) * scale;
    uint32_t new_w = (new.bot_right_x - new.top_left_x) * scale;
    uint32_t new_h = (new.bot_right_y - new.top_left_y) * scale;

    drawRect(fb_x, fb_y,
             fb_x + (old_w > new_w ? old_w : new_w) + scale,
             fb_y + (old_h > new_h ? old_h : new_h) + scale,
             0, FB0);
}

void vid_scale_update_clear(scale2d_params_t old, scale2d_params_t new) {
    uint32_t crop_w = mm_regs->crop_params.bot_right_x - mm_regs->crop_params.top_left_x;
    uint32_t crop_h = mm_regs->crop_params.bot_right_y - mm_regs->crop_params.top_left_y;
    uint32_t fb_x   = mm_regs->fb_pos_params.xpos;
    uint32_t fb_y   = mm_regs->fb_pos_params.ypos;

    uint32_t max_scale = old.scale > new.scale ? old.scale : new.scale;

    drawRect(fb_x, fb_y,
             fb_x + (crop_w * max_scale) + max_scale,
             fb_y + (crop_h * max_scale) + max_scale,
             0, FB0);
}

void vid_fb_pos_update_clear(fb_pos_params_t old, fb_pos_params_t new) {
    uint32_t crop_w = mm_regs->crop_params.bot_right_x - mm_regs->crop_params.top_left_x;
    uint32_t crop_h = mm_regs->crop_params.bot_right_y - mm_regs->crop_params.top_left_y;
    uint32_t scale  = mm_regs->scale_params.scale;
    uint32_t out_w  = crop_w * scale;
    uint32_t out_h  = crop_h * scale;

    uint32_t start_x = old.xpos < new.xpos ? old.xpos : new.xpos;
    uint32_t start_y = old.ypos < new.ypos ? old.ypos : new.ypos;
    uint32_t end_x   = (old.xpos > new.xpos ? old.xpos : new.xpos) + out_w + scale;
    uint32_t end_y   = (old.ypos > new.ypos ? old.ypos : new.ypos) + out_h + scale;

    drawRect(start_x, start_y, end_x, end_y, 0, FB0);
}

// Inc or dec a x|width value based on fraction of current frame width
void vid_x_inc(volatile uint32_t* value, int plus_minus){
  uint16_t width = (mm_regs->crop_params.bot_right_x - mm_regs->crop_params.top_left_x + 1);
  uint16_t inc = width / 15;
  inc = inc > 0 ? inc : 1;
  if(plus_minus==-1){
    if(*value > inc){
      *value -= inc;
    }else{
      *value = 0;
    }
  }else{
    if(*value < (FRAME_WIDTH-inc)){
      *value += inc;
    }else{
      *value = FRAME_WIDTH-1;
    }
  }
}
// Inc or dec a y|height value based on fraction of current frame height
void vid_y_inc(volatile uint32_t* value, int plus_minus){
  uint16_t height = (mm_regs->crop_params.bot_right_y - mm_regs->crop_params.top_left_y + 1);
  uint16_t inc = height / 15;
  inc = inc > 0 ? inc : 1;
  if(plus_minus==-1){
    if(*value > inc){
      *value -= inc;
    }else{
      *value = 0;
    }
  }else{
    if(*value < (FRAME_HEIGHT-inc)){
      *value += inc;
    }else{
      *value = FRAME_HEIGHT-1;
    }
  }
}

// Adjust params based on button press
void vid_crop_size_adjust(uint32_t buttons){
  if(buttons==BTN_U){
    vid_y_inc(&(mm_regs->crop_params.bot_right_y), -1);
  } else if(buttons==BTN_D){
    vid_y_inc(&(mm_regs->crop_params.bot_right_y), 1);
  } else if(buttons==BTN_L){
    vid_x_inc(&(mm_regs->crop_params.bot_right_x), -1);
  } else if(buttons==BTN_R){
    vid_x_inc(&(mm_regs->crop_params.bot_right_x), 1);
  }
}
void vid_crop_pos_adjust(uint32_t buttons){
  if(buttons==BTN_U){
    vid_y_inc(&(mm_regs->crop_params.top_left_y), -1);
    vid_y_inc(&(mm_regs->crop_params.bot_right_y), -1);
  } else if(buttons==BTN_D){
    vid_y_inc(&(mm_regs->crop_params.top_left_y), 1);
    vid_y_inc(&(mm_regs->crop_params.bot_right_y), 1);
  } else if(buttons==BTN_L){
    vid_x_inc(&(mm_regs->crop_params.top_left_x), -1);
    vid_x_inc(&(mm_regs->crop_params.bot_right_x), -1);
  } else if(buttons==BTN_R){
    vid_x_inc(&(mm_regs->crop_params.top_left_x), 1);
    vid_x_inc(&(mm_regs->crop_params.bot_right_x), 1);
  }
}
void vid_scale_adjust(uint32_t buttons){
  if(buttons==BTN_U){
    mm_regs->scale_params.scale += 1;
  } else if(buttons==BTN_D){
    if(mm_regs->scale_params.scale > 1){
      mm_regs->scale_params.scale -= 1;
    }
  }
}
void vid_fb_pos_adjust(uint32_t buttons){
  if(buttons==BTN_U){
    vid_y_inc(&(mm_regs->fb_pos_params.ypos), -1);
  } else if(buttons==BTN_D){
    vid_y_inc(&(mm_regs->fb_pos_params.ypos), 1);
  } else if(buttons==BTN_L){
    vid_x_inc(&(mm_regs->fb_pos_params.xpos), -1);
  } else if(buttons==BTN_R){
    vid_x_inc(&(mm_regs->fb_pos_params.xpos), 1);
  }
}

// Routine for handling button and switches presses
void vid_pipeline_ctrl(){
  // Detect rising edge of buttons // TODO debounce
  static uint32_t buttons_reg = 0;
  uint32_t buttons_rising = mm_regs->status.buttons & ~buttons_reg;
  buttons_reg = mm_regs->status.buttons;

  // Is one of the buttons being pressed?
  if(buttons_rising > 0){
    // What does button press mean
    uint32_t switches = mm_regs->status.switches;
    if(switches == 0b0001){
      crop2d_params_t old_crop = mm_regs->crop_params;
      vid_crop_size_adjust(buttons_rising);
      crop2d_params_t new_crop = mm_regs->crop_params;
      vid_crop_update_clear(old_crop, new_crop);
    }else if(switches == 0b0010){
      crop2d_params_t old_crop = mm_regs->crop_params;
      vid_crop_pos_adjust(buttons_rising);
      crop2d_params_t new_crop = mm_regs->crop_params;
      vid_crop_update_clear(old_crop, new_crop);
    }else if(switches == 0b0100){
      scale2d_params_t old_scale = mm_regs->scale_params;
      vid_scale_adjust(buttons_rising);
      scale2d_params_t new_scale = mm_regs->scale_params;
      vid_scale_update_clear(old_scale, new_scale);
    }else if(switches == 0b1000){
      fb_pos_params_t old_fb_pos = mm_regs->fb_pos_params;
      vid_fb_pos_adjust(buttons_rising);
      fb_pos_params_t new_fb_pos = mm_regs->fb_pos_params;
      vid_fb_pos_update_clear(old_fb_pos, new_fb_pos);
    }
  }
}

// Init ctrl regs
void vid_pipeline_init(){
  mm_regs->crop_params.top_left_x = 0;
  mm_regs->crop_params.top_left_y = 0;
  mm_regs->crop_params.bot_right_x = (FRAME_WIDTH/2) - (FRAME_WIDTH/20);
  mm_regs->crop_params.bot_right_y = (FRAME_HEIGHT/2) - (FRAME_HEIGHT/20);
  mm_regs->scale_params.scale = 1;
  mm_regs->fb_pos_params.xpos = FRAME_WIDTH/2;
  mm_regs->fb_pos_params.ypos = FRAME_HEIGHT/2;
}