#pragma once

#define BTN_U 0b0001
#define BTN_D 0b0010
#define BTN_L 0b0100
#define BTN_R 0b1000

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
      vid_crop_size_adjust(buttons_rising);
    }else if(switches == 0b0010){
      vid_crop_pos_adjust(buttons_rising);
    }else if(switches == 0b0100){
      vid_scale_adjust(buttons_rising);
    }else if(switches == 0b1000){
      vid_fb_pos_adjust(buttons_rising);
    }
  }
}

void vid_pipeline_init(){
  mm_regs->crop_params.top_left_x = 0;
  mm_regs->crop_params.top_left_y = 0;
  mm_regs->crop_params.bot_right_x = (FRAME_WIDTH/2) - (FRAME_WIDTH/20);
  mm_regs->crop_params.bot_right_y = (FRAME_HEIGHT/2) - (FRAME_HEIGHT/20);
  mm_regs->scale_params.scale = 1;
  mm_regs->fb_pos_params.xpos = FRAME_WIDTH/2;
  mm_regs->fb_pos_params.ypos = FRAME_HEIGHT/2;
}