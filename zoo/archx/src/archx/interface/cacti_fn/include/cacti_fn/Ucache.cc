/*------------------------------------------------------------
 *                              CACTI 6.5
 *         Copyright 2008 Hewlett-Packard Development Corporation
 *                         All Rights Reserved
 *
 * Permission to use, copy, and modify this software and its documentation is
 * hereby granted only under the following terms and conditions.  Both the
 * above copyright notice and this permission notice must appear in all copies
 * of the software, derivative works or modified versions, and any portions
 * thereof, and both notices must appear in supporting documentation.
 *
 * Users of this software agree to the terms and conditions set forth herein, and
 * hereby grant back to Hewlett-Packard Company and its affiliated companies ("HP")
 * a non-exclusive, unrestricted, royalty-free right and license under any changes, 
 * enhancements or extensions  made to the core functions of the software, including 
 * but not limited to those affording compatibility with other hardware or software
 * environments, but excluding applications which incorporate this software.
 * Users further agree to use their best efforts to return to HP any such changes,
 * enhancements or extensions that they make and inform HP of noteworthy uses of
 * this software.  Correspondence should be provided to HP at:
 *
 *                       Director of Intellectual Property Licensing
 *                       Office of Strategy and Technology
 *                       Hewlett-Packard Company
 *                       1501 Page Mill Road
 *                       Palo Alto, California  94304
 *
 * This software may be distributed (but not offered for sale or transferred
 * for compensation) to third parties, provided such third parties agree to
 * abide by the terms and conditions of this notice.
 *
 * THE SOFTWARE IS PROVIDED "AS IS" AND HP DISCLAIMS ALL
 * WARRANTIES WITH REGARD TO THIS SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES
 * OF MERCHANTABILITY AND FITNESS.   IN NO EVENT SHALL HP 
 * CORPORATION BE LIABLE FOR ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL
 * DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR
 * PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
 * ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS
 * SOFTWARE.
 *------------------------------------------------------------*/

#include <time.h>
#include <math.h>


#include "area.h"
#include "bank.h"
#include "basic_circuit.h"
#include "component.h"
#include "const.h"
#include "decoder.h"
#include "parameter.h"
#include "Ucache.h"
#include "subarray.h"
#include "uca.h"

#include <pthread.h>
#include <iostream>
#include <algorithm>
#include <list>

using namespace std;

const uint32_t nthreads = NTHREADS;


void min_values_t::update_min_values(const min_values_t * val)
{
  min_delay   = (min_delay > val->min_delay) ? val->min_delay : min_delay;
  min_dyn     = (min_dyn > val->min_dyn) ? val->min_dyn : min_dyn;
  min_leakage = (min_leakage > val->min_leakage) ? val->min_leakage : min_leakage;
  min_area    = (min_area > val->min_area) ? val->min_area : min_area;
  min_cyc     = (min_cyc > val->min_cyc) ? val->min_cyc : min_cyc;
}



void min_values_t::update_min_values(const uca_org_t & res)
{
  min_delay   = (min_delay > res.access_time) ? res.access_time : min_delay;
  min_dyn     = (min_dyn > res.power.readOp.dynamic) ? res.power.readOp.dynamic : min_dyn;
  min_leakage = (min_leakage > res.power.readOp.leakage) ? res.power.readOp.leakage : min_leakage;
  min_area    = (min_area > res.area) ? res.area : min_area;
  min_cyc     = (min_cyc > res.cycle_time) ? res.cycle_time : min_cyc;
}

void min_values_t::update_min_values(const nuca_org_t * res)
{
  min_delay   = (min_delay > res->nuca_pda.delay) ? res->nuca_pda.delay : min_delay;
  min_dyn     = (min_dyn > res->nuca_pda.power.readOp.dynamic) ? res->nuca_pda.power.readOp.dynamic : min_dyn;
  min_leakage = (min_leakage > res->nuca_pda.power.readOp.leakage) ? res->nuca_pda.power.readOp.leakage : min_leakage;
  min_area    = (min_area > res->nuca_pda.area.get_area()) ? res->nuca_pda.area.get_area() : min_area;
  min_cyc     = (min_cyc > res->nuca_pda.cycle_time) ? res->nuca_pda.cycle_time : min_cyc;
}

void min_values_t::update_min_values(const mem_array * res)
{
  min_delay   = (min_delay > res->access_time) ? res->access_time : min_delay;
  min_dyn     = (min_dyn > res->power.readOp.dynamic) ? res->power.readOp.dynamic : min_dyn;
  min_leakage = (min_leakage > res->power.readOp.leakage) ? res->power.readOp.leakage : min_leakage;
  min_area    = (min_area > res->area) ? res->area : min_area;
  min_cyc     = (min_cyc > res->cycle_time) ? res->cycle_time : min_cyc;
}



void * calc_time_mt_wrapper(void * void_obj)
{
  calc_time_mt_wrapper_struct * calc_obj = (calc_time_mt_wrapper_struct *) void_obj;
  uint32_t tid                   = calc_obj->tid;
  list<mem_array *> & data_arr   = calc_obj->data_arr;
  list<mem_array *> & tag_arr    = calc_obj->tag_arr;
  bool is_tag                    = calc_obj->is_tag;
  bool pure_ram                  = calc_obj->pure_ram;
  bool pure_cam					 = calc_obj->pure_cam;
  bool is_main_mem               = calc_obj->is_main_mem;
  double Nspd_min                = calc_obj->Nspd_min;
  min_values_t * data_res        = calc_obj->data_res;
  min_values_t * tag_res         = calc_obj->tag_res;

  data_arr.clear();
  data_arr.push_back(new mem_array);
  tag_arr.clear();
  tag_arr.push_back(new mem_array);

  uint32_t Ndwl_niter = _log2(MAXDATAN) + 1;
  uint32_t Ndbl_niter = _log2(MAXDATAN) + 1;
  uint32_t Ndcm_niter = _log2(MAX_COL_MUX) + 1;
  uint32_t niter      = Ndwl_niter * Ndbl_niter * Ndcm_niter;


  bool is_valid_partition;
  int wt_min, wt_max;
/*
  if (g_ip->force_wiretype) {
    if (g_ip->wt == 0) {
      wt_min = Low_swing;
      wt_max = Low_swing;
    }
    else {
      wt_min = Global;
      wt_max = Low_swing-1;
    }
  }
  else {
    wt_min = Global;
    wt_max = Low_swing;
  }
*/

  //Divya adding this
  if (!g_ip->force_wiretype) {
	  wt_min = Global;
	  wt_max = Low_swing;
  }
  else  { //force_wiretype == true
	  wt_min = g_ip->wt;
	  wt_max = g_ip->wt;
  }

//  if(g_ip->force_cache_config)
//  cout << "ucache.cc force config: " << g_ip->force_cache_config << ", ndbl: " << g_ip->ndbl << ", ndwl: " << g_ip->ndwl <<
//		  ", nspd: " << g_ip->nspd << ", ndcm: " << g_ip->nspd << ", sam1: " << g_ip->ndsam1 << ", sam2: " << g_ip->ndsam2 << endl;

  for (double Nspd = Nspd_min; Nspd <= MAXDATASPD; Nspd *= 2)
  {
    for (int wr = wt_min; wr <= wt_max; wr++) 
    {
      for (uint32_t iter = tid; iter < niter; iter += nthreads)
      {
        // reconstruct Ndwl, Ndbl, Ndcm
        unsigned int Ndwl = 1 << (iter / (Ndbl_niter * Ndcm_niter));
        unsigned int Ndbl = 1 << ((iter / (Ndcm_niter))%Ndbl_niter);
        unsigned int Ndcm = 1 << (iter % Ndcm_niter); 
        for(unsigned int Ndsam_lev_1 = 1; Ndsam_lev_1 <= MAX_COL_MUX; Ndsam_lev_1 *= 2)
        {
          for(unsigned int Ndsam_lev_2 = 1; Ndsam_lev_2 <= MAX_COL_MUX; Ndsam_lev_2 *= 2)
          {
            //for debuging
        	  //Divya changing this so that Tag array parameters also take same value as data array parameters in force_onfig is true
            if (g_ip->force_cache_config)// && is_tag == false) //if (g_ip->force_cache_config && is_tag == false) //divya
            {
       		  wr   = g_ip->wt;
 //      		  cout << "wire: " << wr << endl;
       		  if(is_tag == false) { //divya added this line
				  Ndwl = g_ip->ndwl;
				  Ndbl = g_ip->ndbl;
				  Ndcm = g_ip->ndcm;
				  if(g_ip->nspd != 0) {
					Nspd = g_ip->nspd;
				  }
				  if(g_ip->ndsam1 != 0) {
					Ndsam_lev_1 = g_ip->ndsam1;
					Ndsam_lev_2 = g_ip->ndsam2;
				  }
//	              	cout << "data array:  Nspd : " << Nspd << " Ndbl : " <<  Ndbl
//	             			<<  " Ndwl : " <<  Ndwl<< " Ndcm : " << Ndcm << " Ndsam1 : " << Ndsam_lev_1 << " Ndsam2 : " << Ndsam_lev_2 << endl;

       		  }
       		  //Divya adding tag params
       		  else { //is_tag == true
       			 Ndwl = g_ip->ntwl;
				  Ndbl = g_ip->ntbl;
				  Ndcm = g_ip->ntcm;
				  if(g_ip->ntspd != 0) {
					Nspd = g_ip->ntspd;
				  }
				  if(g_ip->ntsam1 != 0) {
					Ndsam_lev_1 = g_ip->ntsam1;
					Ndsam_lev_2 = g_ip->ntsam2;
				  }
//	              	cout << "tag array:  Nspd : " << Nspd << " Ndbl : " <<  Ndbl
//	             			<<  " Ndwl : " <<  Ndwl<< " Ndcm : " << Ndcm << " Ndsam1 : " << Ndsam_lev_1 << " Ndsam2 : " << Ndsam_lev_2 << endl;
       		  }//divya added end
            }
            // Divya adding to propagate wire signalling effect when force_cache_config is false
            else {
            	g_ip->wt = (enum Wire_type) wr;
            }

            if (is_tag == true)
            {
//            	if(g_ip->force_cache_config)
//               	cout << "tag partition : " << is_valid_partition << " Nspd : " << Nspd << " Ndbl : " <<  Ndbl
//             			<<  " Ndwl : " <<  Ndwl<< " Ndcm : " << Ndcm << " Ndsam1 : " << Ndsam_lev_1 << " Ndsam2 : " << Ndsam_lev_2 << endl;

               	is_valid_partition = calculate_time(is_tag, pure_ram,pure_cam, Nspd, Ndwl,
                  Ndbl, Ndcm, Ndsam_lev_1, Ndsam_lev_2,
                  tag_arr.back(), 0, NULL, NULL,
                  is_main_mem);
            }
            // If it's a fully-associative cache, the data array partition parameters are identical to that of
            // the tag array, so compute data array partition properties also here.
            if (is_tag == false || g_ip->fully_assoc)
            {
 //           	if(g_ip->force_cache_config)
 //            	cout << "data partition : " << is_valid_partition << " Nspd : " << Nspd << " Ndbl : " <<  Ndbl
 //            			<<  " Ndwl : " <<  Ndwl<< " Ndcm : " << Ndcm << " Ndsam1 : " << Ndsam_lev_1 << " Ndsam2 : " << Ndsam_lev_2 << endl;

             	is_valid_partition = calculate_time(is_tag/*false*/, pure_ram,pure_cam, Nspd, Ndwl,
                  Ndbl, Ndcm, Ndsam_lev_1, Ndsam_lev_2,
                  data_arr.back(), 0, NULL, NULL,
                  is_main_mem);
              }

            if (is_valid_partition)
            {
              if (is_tag == true)
              {
           //   	cout << "tag partition valid \n";
//               	cout << "tag partition : " << is_valid_partition <<  " Ntwl : " <<  Ndwl  << " Ntbl : " <<  Ndbl
//            			<< " Ntspd : " << Nspd << " Ntcm : " << Ndcm << " Ntsam1 : " << Ndsam_lev_1 << " Ntsam2 : " << Ndsam_lev_2 << endl;

                tag_arr.back()->wt = (enum Wire_type) wr;
                tag_res->update_min_values(tag_arr.back());
                tag_arr.push_back(new mem_array);
              }
              if (is_tag == false || g_ip->fully_assoc)
              {
           //   	cout << "data partition valid \n";
//                 	cout << "data partition : " << is_valid_partition <<  " Ndwl : " <<  Ndwl  << " Ndbl : " <<  Ndbl
//               			<< " Nspd : " << Nspd << " Ndcm : " << Ndcm << " Ndsam1 : " << Ndsam_lev_1 << " Ndsam2 : " << Ndsam_lev_2 << endl;

                data_arr.back()->wt = (enum Wire_type) wr;
                data_res->update_min_values(data_arr.back());
                data_arr.push_back(new mem_array);
              }
            }

            //Divya changing this so that Tag array parameters also take same value as data array parameters in force_onfig is true
            if (g_ip->force_cache_config) // && is_tag == false) //if (g_ip->force_cache_config && is_tag == false) //original.
            {
              wr   = wt_max;
              iter = niter;
              if(g_ip->nspd != 0) {
                Nspd = MAXDATASPD;
              }
              if (g_ip->ndsam1 != 0) {
                Ndsam_lev_1 = MAX_COL_MUX+1;
                Ndsam_lev_2 = MAX_COL_MUX+1;
              }
            }
          }
        }
      }
    }
  }

  delete data_arr.back();
  delete tag_arr.back();
  data_arr.pop_back();
  tag_arr.pop_back();

  pthread_exit(NULL);
}



bool calculate_time(
    bool is_tag,
    int pure_ram,
    bool pure_cam,
    double Nspd,
    unsigned int Ndwl, 
    unsigned int Ndbl,
    unsigned int Ndcm,
    unsigned int Ndsam_lev_1,
    unsigned int Ndsam_lev_2,
    mem_array *ptr_array,
    int flag_results_populate,
    results_mem_array *ptr_results,
    uca_org_t *ptr_fin_res,
    bool is_main_mem)
{
  DynamicParameter dyn_p(is_tag, pure_ram, pure_cam, Nspd, Ndwl, Ndbl, Ndcm, Ndsam_lev_1, Ndsam_lev_2, is_main_mem);
  if (dyn_p.is_valid == false)
  {
//	  cout << "tag : " << is_tag << "dynp invalid \n";
    return false;
  }

  UCA * uca = new UCA(dyn_p);
//  cout << "exiting uca \n";

  if (flag_results_populate)
  { //For the final solution, populate the ptr_results data structure  -- TODO: copy only necessary variables
  }
  else
  {
	  collect_uca_results(Nspd, Ndwl, Ndbl, Ndcm, Ndsam_lev_1, Ndsam_lev_2, uca, ptr_array, is_main_mem);
/*//Divya moving these values to collect_uca_results() function
    ptr_array->Ndwl = Ndwl;
    ptr_array->Ndbl = Ndbl;
    ptr_array->Nspd = Nspd;
    ptr_array->deg_bl_muxing = dyn_p.deg_bl_muxing;
    ptr_array->Ndsam_lev_1 = Ndsam_lev_1;
    ptr_array->Ndsam_lev_2 = Ndsam_lev_2;
    ptr_array->access_time = uca->access_time;
    ptr_array->cycle_time = uca->cycle_time;
    ptr_array->multisubbank_interleave_cycle_time = uca->multisubbank_interleave_cycle_time;
    ptr_array->area_ram_cells = uca->area_all_dataramcells;
    ptr_array->area   = uca->area.get_area();
    ptr_array->height = uca->area.h;
    ptr_array->width  = uca->area.w;
    ptr_array->mat_height = uca->bank.mat.area.h;
    ptr_array->mat_length = uca->bank.mat.area.w;
    ptr_array->subarray_height = uca->bank.mat.subarray.area.h;
    ptr_array->subarray_length = uca->bank.mat.subarray.area.w;
    ptr_array->power  = uca->power;
    ptr_array->delay_senseamp_mux_decoder =
      MAX(uca->delay_array_to_sa_mux_lev_1_decoder,
          uca->delay_array_to_sa_mux_lev_2_decoder);
    ptr_array->delay_before_subarray_output_driver         = uca->delay_before_subarray_output_driver;
    ptr_array->delay_from_subarray_output_driver_to_output = uca->delay_from_subarray_out_drv_to_out;

    ptr_array->delay_route_to_bank          = uca->htree_in_add->delay;
    ptr_array->delay_input_htree            = uca->bank.htree_in_add->delay;
    ptr_array->delay_row_predecode_driver_and_block = uca->bank.mat.r_predec->delay;
    ptr_array->delay_row_decoder            = uca->bank.mat.row_dec->delay;
    ptr_array->delay_bitlines               = uca->bank.mat.delay_bitline;
    ptr_array->delay_sense_amp              = uca->bank.mat.delay_sa;
    ptr_array->delay_subarray_output_driver = uca->bank.mat.delay_subarray_out_drv_htree;
    ptr_array->delay_dout_htree             = uca->bank.htree_out_data->delay;
    ptr_array->delay_comparator             = uca->bank.mat.delay_comparator;

    ptr_array->all_banks_height = uca->area.h;
    ptr_array->all_banks_width  = uca->area.w;    
    ptr_array->area_efficiency = uca->area_all_dataramcells * 100 / (uca->area.get_area());

    ptr_array->power_routing_to_bank = uca->power_routing_to_bank;
    ptr_array->power_addr_input_htree = uca->bank.htree_in_add->power;
    ptr_array->power_data_input_htree = uca->bank.htree_in_data->power;
    ptr_array->power_data_output_htree = uca->bank.htree_out_data->power;

    ptr_array->power_row_predecoder_drivers.readOp.dynamic = uca->bank.mat.r_predec->driver_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_row_predecoder_blocks.readOp.dynamic = uca->bank.mat.r_predec->block_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;

    ptr_array->power_row_decoders.readOp.dynamic = uca->bank.mat.power_row_decoders.readOp.dynamic * dyn_p.num_act_mats_hor_dir;

    ptr_array->power_bit_mux_predecoder_drivers.readOp.dynamic = uca->bank.mat.b_mux_predec->driver_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_bit_mux_predecoder_blocks.readOp.dynamic  = uca->bank.mat.b_mux_predec->block_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_bit_mux_decoders.readOp.dynamic = uca->bank.mat.power_bit_mux_decoders.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_senseamp_mux_lev_1_predecoder_drivers.readOp.dynamic = uca->bank.mat.sa_mux_lev_1_predec->driver_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic = uca->bank.mat.sa_mux_lev_1_predec->block_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_senseamp_mux_lev_1_decoders.readOp.dynamic = uca->bank.mat.power_sa_mux_lev_1_decoders.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic = uca->bank.mat.sa_mux_lev_2_predec->driver_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic = uca->bank.mat.sa_mux_lev_2_predec->block_power.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_senseamp_mux_lev_2_decoders.readOp.dynamic = uca->bank.mat.power_sa_mux_lev_2_decoders.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_bitlines.readOp.dynamic = uca->bank.mat.power_bitline.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_sense_amps.readOp.dynamic = uca->bank.mat.power_sa.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_prechg_eq_drivers.readOp.dynamic = uca->bank.mat.power_bl_precharge_eq_drv.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_output_drivers_at_subarray.readOp.dynamic = uca->bank.mat.power_subarray_out_drv.readOp.dynamic * dyn_p.num_act_mats_hor_dir;
    ptr_array->power_comparators.readOp.dynamic = uca->bank.mat.power_comparator.readOp.dynamic * dyn_p.num_act_mats_hor_dir;

    ptr_array->activate_energy = uca->activate_energy;
    ptr_array->read_energy = uca->read_energy;
    ptr_array->write_energy = uca->write_energy;
    ptr_array->precharge_energy = uca->precharge_energy;
    ptr_array->refresh_power = uca->refresh_power;
    ptr_array->leak_power_subbank_closed_page = uca->leak_power_subbank_closed_page;
    ptr_array->leak_power_subbank_open_page = uca->leak_power_subbank_open_page;
    ptr_array->leak_power_request_and_reply_networks = uca->leak_power_request_and_reply_networks;

    ptr_array->precharge_delay = uca->precharge_delay;
	 
  // Alireza - Begin
    ptr_array->leak_power_bank = uca->bank.power.readOp.leakage;
    ptr_array->leak_power_mat = uca->bank.mat.power.readOp.leakage;
    ptr_array->leak_power_sram_cell = uca->bank.mat.leak_power_sram_cell;
    ptr_array->leak_power_mem_array = uca->bank.mat.power_bitline.readOp.leakage;
	 
    ptr_array->subarray_num_rows = uca->bank.mat.subarray.num_rows;
    ptr_array->subarray_num_cols = uca->bank.mat.subarray.num_cols;
    ptr_array->num_subarrays_per_mat = uca->bank.mat.num_subarrays_per_mat;
  // Alireza - End
*/
  }

  delete uca;
  return true;
}

//Divya added 11-11-2020
void collect_uca_results(
    double Nspd,
    unsigned int Ndwl,
    unsigned int Ndbl,
    unsigned int Ndcm,
    unsigned int Ndsam_lev_1,
    unsigned int Ndsam_lev_2,
    UCA const * const uca,
    mem_array * const ptr_array,
    bool is_main_mem)
{
	int num_act_mats_hor_dir = uca->bank.dp.num_act_mats_hor_dir;
	int num_mats = uca->bank.dp.num_mats;
	  bool is_fa = uca->bank.dp.fully_assoc;
	  bool pure_cam = uca->bank.dp.pure_cam;

	   ptr_array->Ndwl = Ndwl;
	    ptr_array->Ndbl = Ndbl;
	    ptr_array->Nspd = Nspd;
	    ptr_array->deg_bl_muxing = uca->bank.dp.deg_bl_muxing;
	    ptr_array->Ndsam_lev_1 = Ndsam_lev_1;
	    ptr_array->Ndsam_lev_2 = Ndsam_lev_2;
	    ptr_array->access_time = uca->access_time;
	    ptr_array->cycle_time = uca->cycle_time;
	    ptr_array->multisubbank_interleave_cycle_time = uca->multisubbank_interleave_cycle_time;
	    ptr_array->area_ram_cells = uca->area_all_dataramcells;
	    ptr_array->area   = uca->area.get_area();
	    ptr_array->height = uca->area.h;
	    ptr_array->width  = uca->area.w;
	    ptr_array->mat_height = uca->bank.mat.area.h;
	    ptr_array->mat_length = uca->bank.mat.area.w;
	    ptr_array->subarray_height = uca->bank.mat.subarray.area.h;
	    ptr_array->subarray_length = uca->bank.mat.subarray.area.w;
	    ptr_array->power  = uca->power;
	    ptr_array->delay_senseamp_mux_decoder =
	      MAX(uca->delay_array_to_sa_mux_lev_1_decoder,
	          uca->delay_array_to_sa_mux_lev_2_decoder);
	    ptr_array->delay_before_subarray_output_driver         = uca->delay_before_subarray_output_driver;
	    ptr_array->delay_from_subarray_output_driver_to_output = uca->delay_from_subarray_out_drv_to_out;

	    ptr_array->delay_route_to_bank          = uca->htree_in_add->delay;
	    ptr_array->delay_input_htree            = uca->bank.htree_in_add->delay;
	    ptr_array->delay_row_predecode_driver_and_block = uca->bank.mat.r_predec->delay;
	    ptr_array->delay_row_decoder            = uca->bank.mat.row_dec->delay;
	    ptr_array->delay_bitlines               = uca->bank.mat.delay_bitline;
	    ptr_array->delay_matchlines               = uca->bank.mat.delay_matchchline;
	    ptr_array->delay_sense_amp              = uca->bank.mat.delay_sa;
	    ptr_array->delay_subarray_output_driver = uca->bank.mat.delay_subarray_out_drv_htree;
	    ptr_array->delay_dout_htree             = uca->bank.htree_out_data->delay;
	    ptr_array->delay_comparator             = uca->bank.mat.delay_comparator;

	    ptr_array->all_banks_height = uca->area.h;
	    ptr_array->all_banks_width  = uca->area.w;
	    ptr_array->area_efficiency = uca->area_all_dataramcells * 100 / (uca->area.get_area());

	    ptr_array->power_routing_to_bank = uca->power_routing_to_bank;
	    ptr_array->power_addr_input_htree = uca->bank.htree_in_add->power;
	    ptr_array->power_data_input_htree = uca->bank.htree_in_data->power;
	    ptr_array->power_data_output_htree = uca->bank.htree_out_data->power;

	    ptr_array->power_row_predecoder_drivers = uca->bank.mat.r_predec->driver_power;
	    ptr_array->power_row_predecoder_drivers.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_row_predecoder_drivers.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_row_predecoder_drivers.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_row_predecoder_blocks = uca->bank.mat.r_predec->block_power;
	    ptr_array->power_row_predecoder_blocks.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_row_predecoder_blocks.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_row_predecoder_blocks.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_row_decoders = uca->bank.mat.power_row_decoders;
	    ptr_array->power_row_decoders.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_row_decoders.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_row_decoders.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_bit_mux_predecoder_drivers = uca->bank.mat.b_mux_predec->driver_power;
	    ptr_array->power_bit_mux_predecoder_drivers.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bit_mux_predecoder_drivers.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bit_mux_predecoder_drivers.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_bit_mux_predecoder_blocks  = uca->bank.mat.b_mux_predec->block_power;
	    ptr_array->power_bit_mux_predecoder_blocks.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bit_mux_predecoder_blocks.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bit_mux_predecoder_blocks.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_bit_mux_decoders = uca->bank.mat.power_bit_mux_decoders;
	    ptr_array->power_bit_mux_decoders.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bit_mux_decoders.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bit_mux_decoders.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_senseamp_mux_lev_1_predecoder_drivers = uca->bank.mat.sa_mux_lev_1_predec->driver_power;
	    ptr_array->power_senseamp_mux_lev_1_predecoder_drivers .readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_1_predecoder_drivers .writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_1_predecoder_drivers .searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_senseamp_mux_lev_1_predecoder_blocks = uca->bank.mat.sa_mux_lev_1_predec->block_power;
	    ptr_array->power_senseamp_mux_lev_1_predecoder_blocks.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_1_predecoder_blocks.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_1_predecoder_blocks.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_senseamp_mux_lev_1_decoders = uca->bank.mat.power_sa_mux_lev_1_decoders;
	    ptr_array->power_senseamp_mux_lev_1_decoders.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_1_decoders.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_1_decoders.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_senseamp_mux_lev_2_predecoder_drivers = uca->bank.mat.sa_mux_lev_2_predec->driver_power;
	    ptr_array->power_senseamp_mux_lev_2_predecoder_drivers.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_2_predecoder_drivers.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_2_predecoder_drivers.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_senseamp_mux_lev_2_predecoder_blocks = uca->bank.mat.sa_mux_lev_2_predec->block_power;
	    ptr_array->power_senseamp_mux_lev_2_predecoder_blocks.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_2_predecoder_blocks.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_2_predecoder_blocks.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_senseamp_mux_lev_2_decoders = uca->bank.mat.power_sa_mux_lev_2_decoders;
	    ptr_array->power_senseamp_mux_lev_2_decoders .readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_2_decoders .writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_senseamp_mux_lev_2_decoders .searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_bitlines = uca->bank.mat.power_bitline;
	    ptr_array->power_bitlines.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bitlines.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_bitlines.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_sense_amps = uca->bank.mat.power_sa;
	    ptr_array->power_sense_amps.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_sense_amps.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_sense_amps.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_prechg_eq_drivers = uca->bank.mat.power_bl_precharge_eq_drv;
	    ptr_array->power_prechg_eq_drivers.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_prechg_eq_drivers.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_prechg_eq_drivers.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_output_drivers_at_subarray = uca->bank.mat.power_subarray_out_drv;
	    ptr_array->power_output_drivers_at_subarray.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_output_drivers_at_subarray.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_output_drivers_at_subarray.searchOp.dynamic *= num_act_mats_hor_dir;

	    ptr_array->power_comparators = uca->bank.mat.power_comparator;
	    ptr_array->power_comparators.readOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_comparators.writeOp.dynamic *= num_act_mats_hor_dir;
	    ptr_array->power_comparators.searchOp.dynamic *= num_act_mats_hor_dir;

	    if (is_fa || pure_cam)
	    {
			ptr_array->power_htree_in_search = uca->bank.htree_in_search->power;
		//    cout<<"power_htree_in_search"<<uca->bank.htree_in_search->power.readOp.leakage<<endl;
			ptr_array->power_htree_out_search = uca->bank.htree_out_search->power;
		//    cout<<"power_htree_out_search"<<uca->bank.htree_out_search->power.readOp.leakage<<endl;
			ptr_array->power_searchline = uca->bank.mat.power_searchline;
		//    cout<<"power_searchlineh"<<uca->bank.mat.power_searchline.readOp.leakage<<endl;
			ptr_array->power_searchline.searchOp.dynamic *= num_mats;
			ptr_array->power_searchline_precharge = uca->bank.mat.power_searchline_precharge;
			ptr_array->power_searchline_precharge.searchOp.dynamic *= num_mats;
			ptr_array->power_matchlines = uca->bank.mat.power_matchline;
			ptr_array->power_matchlines.searchOp.dynamic *= num_mats;
			ptr_array->power_matchline_precharge = uca->bank.mat.power_matchline_precharge;
			ptr_array->power_matchline_precharge.searchOp.dynamic *= num_mats;
			ptr_array->power_matchline_to_wordline_drv = uca->bank.mat.power_ml_to_ram_wl_drv;
		//    cout<<"power_matchline.searchOp.leakage"<<uca->bank.mat.power_matchline.searchOp.leakage<<endl;
	    }

	    ptr_array->activate_energy = uca->activate_energy;
	    ptr_array->read_energy = uca->read_energy;
	    ptr_array->write_energy = uca->write_energy;
	    ptr_array->precharge_energy = uca->precharge_energy;
	    ptr_array->refresh_power = uca->refresh_power;
	    ptr_array->leak_power_subbank_closed_page = uca->leak_power_subbank_closed_page;
	    ptr_array->leak_power_subbank_open_page = uca->leak_power_subbank_open_page;
	    ptr_array->leak_power_request_and_reply_networks = uca->leak_power_request_and_reply_networks;

	    ptr_array->precharge_delay = uca->precharge_delay;

		ptr_array->array_leakage= uca->bank.array_leakage;
		ptr_array->wl_leakage= uca->bank.wl_leakage;
		ptr_array->cl_leakage= uca->bank.cl_leakage;

	  // Alireza - Begin
	    ptr_array->leak_power_bank = uca->bank.power.readOp.leakage;
	    ptr_array->leak_power_mat = uca->bank.mat.power.readOp.leakage;
	    ptr_array->leak_power_sram_cell = uca->bank.mat.leak_power_sram_cell;
	    ptr_array->leak_power_mem_array = uca->bank.mat.power_bitline.readOp.leakage;

	    ptr_array->subarray_num_rows = uca->bank.mat.subarray.num_rows;
	    ptr_array->subarray_num_cols = uca->bank.mat.subarray.num_cols;
	    ptr_array->num_subarrays_per_mat = uca->bank.mat.num_subarrays_per_mat;
	  // Alireza - End
}
//Divye end

bool check_uca_org(uca_org_t & u, min_values_t & minval)
{
  if (((u.access_time - minval.min_delay)*100/minval.min_delay) > g_ip->delay_dev) {
    return false;
  }
  if (((u.power.readOp.dynamic - minval.min_dyn)/minval.min_dyn)*100 >
      g_ip->dynamic_power_dev) {
    return false;
  }
  if (((u.power.readOp.leakage - minval.min_leakage)/minval.min_leakage)*100 >
      g_ip->leakage_power_dev) {
    return false;
  }
  if (((u.cycle_time - minval.min_cyc)/minval.min_cyc)*100 >
      g_ip->cycle_time_dev) {
    return false;
  }
  if (((u.area - minval.min_area)/minval.min_area)*100 >
      g_ip->area_dev) {
    return false;
  }
  return true;
}

bool check_mem_org(mem_array & u, const min_values_t & minval)
{
  if (((u.access_time - minval.min_delay)*100/minval.min_delay) > g_ip->delay_dev) {
    return false;
  }
  if (((u.power.readOp.dynamic - minval.min_dyn)/minval.min_dyn)*100 >
      g_ip->dynamic_power_dev) {
    return false;
  }
  if (((u.power.readOp.leakage - minval.min_leakage)/minval.min_leakage)*100 >
      g_ip->leakage_power_dev) {
    return false;
  }
  if (((u.cycle_time - minval.min_cyc)/minval.min_cyc)*100 >
      g_ip->cycle_time_dev) {
    return false;
  }
  if (((u.area - minval.min_area)/minval.min_area)*100 >
      g_ip->area_dev) {
    return false;
  }
  return true;
}


void find_optimal_uca(uca_org_t *res, min_values_t & minval, list<uca_org_t> & ulist)
{
  double cost = 0;
  double min_cost = BIGNUM;
  float d, a, dp, lp, c;
//  int count = 0; 	//divya
  dp = g_ip->dynamic_power_wt;
  lp = g_ip->leakage_power_wt;
  a  = g_ip->area_wt;
  d  = g_ip->delay_wt;
  c  = g_ip->cycle_time_wt;

  if (ulist.empty() == true)
  {
    cout << "ERROR: no valid cache organizations found" << endl;
    exit(0);
  }

  for (list<uca_org_t>::iterator niter = ulist.begin(); niter != ulist.end(); niter++)
  { 
    if (g_ip->ed == 1)
    {
      cost = ((niter)->access_time/minval.min_delay) * ((niter)->power.readOp.dynamic/minval.min_dyn);
      if (min_cost > cost)
      {
        min_cost = cost;
        *res = (*(niter));
      }
/*
      cout << "(niter)->access_time : " << (niter)->access_time <<
    		  ", minval.min_delay : " << minval.min_delay <<
			  ", (niter)->power.readOp.dynamic : " << (niter)->power.readOp.dynamic <<
			  ", minval.min_dyn : " << minval.min_dyn <<
			  ", (niter)->access_time/minval.min_delay) : " << ((niter)->access_time/minval.min_delay) <<
				", ((niter)->power.readOp.dynamic/minval.min_dyn) : " << ((niter)->power.readOp.dynamic/minval.min_dyn)
				<< ", cost : " << cost<< endl;
*/
    }
    else if (g_ip->ed == 2)
    {
      cost = ((niter)->access_time/minval.min_delay)*
             ((niter)->access_time/minval.min_delay)*
             ((niter)->power.readOp.dynamic/minval.min_dyn);
      if (min_cost > cost)
      {
        min_cost = cost;
        *res = (*(niter));
      }
    }
    else
    {
      /* 
       * check whether the current organization
       * meets the input deviation constraints
       */
      bool v = check_uca_org(*niter, minval);
      if (minval.min_leakage == 0) minval.min_leakage = 0.1; //FIXME remove this after leakage modeling

      if (v)
      {
        cost = (d  * ((niter)->access_time/minval.min_delay) +
                c  * ((niter)->cycle_time/minval.min_cyc) +
                dp * ((niter)->power.readOp.dynamic/minval.min_dyn) +
                lp * ((niter)->power.readOp.leakage/minval.min_leakage) +
                a  * ((niter)->area/minval.min_area));
        //fprintf(stderr, "cost = %g\n", cost);

        if (min_cost > cost) {
          min_cost = cost;
          *res = (*(niter));
          niter = ulist.erase(niter);
          niter--;
        }
      }
      else {
        niter = ulist.erase(niter);
        if(niter != ulist.begin())
          niter--;
      }
    }
  }

  if (min_cost == BIGNUM)
  {
    cout << "ERROR: no cache organizations met optimization criteria" << endl;
    exit(0);
  }
}



void filter_tag_arr(const min_values_t & min, list<mem_array *> & list)
{
  double cost = BIGNUM;
  double cur_cost;
  double wt_delay = g_ip->delay_wt, wt_dyn = g_ip->dynamic_power_wt, wt_leakage = g_ip->leakage_power_wt, wt_cyc = g_ip->cycle_time_wt, wt_area = g_ip->area_wt;
  mem_array * res = NULL; 

  if (list.empty() == true)
  {
    cout << "ERROR: no valid tag organizations found: empty list" << endl;
    exit(1);
  }


  while (list.empty() != true)
  {
    bool v = check_mem_org(*list.back(), min);
    if (v) 
    {
      cur_cost = wt_delay   * (list.back()->access_time/min.min_delay) +
        wt_dyn     * (list.back()->power.readOp.dynamic/min.min_dyn) +
        wt_leakage * (list.back()->power.readOp.leakage/min.min_leakage) +
        wt_area    * (list.back()->area/min.min_area) +
        wt_cyc     * (list.back()->cycle_time/min.min_cyc);
    }
    else 
    {
      cur_cost = BIGNUM;
    }
    if (cur_cost < cost)
    {
      if (res != NULL)
      {
        delete res;
      }
      cost = cur_cost;
      res  = list.back();
    }
    else
    {
      delete list.back();
    }
    list.pop_back();
  }
  if(!res) 
  {
    cout << "ERROR: no valid tag organizations found: result NULL" << endl;
    exit(0);
  }

  list.push_back(res);
}



void filter_data_arr(list<mem_array *> & curr_list)
{
  if (curr_list.empty() == true)
  {
    cout << "ERROR: no valid data array organizations found" << endl;
    exit(1);
  }

  list<mem_array *>::iterator iter;

  for (iter = curr_list.begin(); iter != curr_list.end(); ++iter)
  {
    mem_array * m = *iter;

    if (m == NULL) exit(1);
  
    if(((m->access_time - m->arr_min.min_delay)/m->arr_min.min_delay > 0.5) &&
       ((m->power.readOp.dynamic - m->arr_min.min_dyn)/m->arr_min.min_dyn > 0.5))
    {
      delete m;
      iter = curr_list.erase(iter);
      iter --;
    }
  }
}



/* 
 * Performs exhaustive search across different sub-array sizes, 
 * wire types and aspect ratios to find an optimal UCA organization
 * 1. First different valid tag array organizations are calculated
 *    and stored in tag_arr array
 * 2. The exhaustive search is repeated to find valid data array
 *    organizations and stored in data_arr array
 * 3. Cache area, delay, power, and cycle time for different
 *    cache organizations are calculated based on the 
 *    above results 
 * 4. Cache model with least cost is picked from sol_list
 */
void solve(uca_org_t *fin_res)
{
  bool   is_dram  = false;
  int    pure_ram = g_ip->pure_ram;
  bool   pure_cam = g_ip->pure_cam;

//  init_tech_params(g_ip->F_sz_um, false);
  init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //divya added wire technology

  list<mem_array *> tag_arr (0);
  list<mem_array *> data_arr(0);
  list<mem_array *>::iterator miter;
  list<uca_org_t> sol_list(1, uca_org_t());

  fin_res->tag_array.access_time = 0;
  fin_res->tag_array.Ndwl = 0;
  fin_res->tag_array.Ndbl = 0;
  fin_res->tag_array.Nspd = 0;
  fin_res->tag_array.deg_bl_muxing = 0;
  fin_res->tag_array.Ndsam_lev_1 = 0;
  fin_res->tag_array.Ndsam_lev_2 = 0;

//  cout << "solve intialized\n";

  // distribute calculate_time() execution to multiple threads
  calc_time_mt_wrapper_struct * calc_array = new calc_time_mt_wrapper_struct[nthreads];
  pthread_t threads[nthreads];

  for (uint32_t t = 0; t < nthreads; t++)
  {
    calc_array[t].tid         = t;
    calc_array[t].pure_ram    = pure_ram;
    calc_array[t].pure_cam    = pure_cam;
    calc_array[t].data_res    = new min_values_t();
    calc_array[t].tag_res     = new min_values_t();
  }

  bool     is_tag;
  uint32_t ram_cell_tech_type;

  // If it's a cache, first calculate the area, delay and power for all tag array partitions.
  if (!(pure_ram||pure_cam||g_ip->fully_assoc))
  { //cache
    is_tag              = true;
    ram_cell_tech_type  = g_ip->tag_arr_ram_cell_tech_type;
    is_dram             = ((ram_cell_tech_type == lp_dram) || (ram_cell_tech_type == comm_dram));
//    init_tech_params(g_ip->F_sz_um, is_tag);
    init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //divya added wire technology

    for (uint32_t t = 0; t < nthreads; t++)
    {
      calc_array[t].is_tag      = is_tag;
      calc_array[t].is_main_mem = false;
      calc_array[t].Nspd_min    = 0.125;
      pthread_create(&threads[t], NULL, calc_time_mt_wrapper, (void *)(&(calc_array[t])));
    }

    for (uint32_t t = 0; t < nthreads; t++)
    {
      pthread_join(threads[t], NULL);
    }

    for (uint32_t t = 0; t < nthreads; t++)
    {
      calc_array[t].data_arr.sort(mem_array::lt);
      data_arr.merge(calc_array[t].data_arr, mem_array::lt);
      calc_array[t].tag_arr.sort(mem_array::lt);
      tag_arr.merge(calc_array[t].tag_arr, mem_array::lt);
    }
  }

  // calculate the area, delay and power for all data array partitions (for cache or plain RAM).
//  if (!g_ip->fully_assoc)
//  {
    is_tag              = false;
    ram_cell_tech_type  = g_ip->data_arr_ram_cell_tech_type;
    is_dram             = ((ram_cell_tech_type == lp_dram) || (ram_cell_tech_type == comm_dram));
//    init_tech_params(g_ip->F_sz_um, is_tag);
    init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, false); //divya added wire technology

    for (uint32_t t = 0; t < nthreads; t++)
    {
      calc_array[t].is_tag      = is_tag;
      calc_array[t].is_main_mem = g_ip->is_main_mem;
      if (!(pure_cam||g_ip->fully_assoc))
    	  calc_array[t].Nspd_min    = (double)(g_ip->out_w)/(double)(g_ip->block_sz*8);
      else
    	  calc_array[t].Nspd_min    = 1;
      pthread_create(&threads[t], NULL, calc_time_mt_wrapper, (void *)(&(calc_array[t])));
    }

    for (uint32_t t = 0; t < nthreads; t++)
    {
      pthread_join(threads[t], NULL);
    }

    data_arr.clear();
    for (uint32_t t = 0; t < nthreads; t++)
    {
      calc_array[t].data_arr.sort(mem_array::lt);
      data_arr.merge(calc_array[t].data_arr, mem_array::lt);
    }
//  }

  min_values_t d_min =  min_values_t();
  min_values_t t_min =  min_values_t();
  min_values_t cache_min =  min_values_t();

  for (uint32_t t = 0; t < nthreads; t++) 
  {
    d_min.update_min_values(calc_array[t].data_res);
    t_min.update_min_values(calc_array[t].tag_res);
  }

  for (miter = data_arr.begin(); miter != data_arr.end(); miter++)
  {
    (*miter)->arr_min = d_min;
  }

  //cout << data_arr.size() << "\t" << tag_arr.size() <<" before\n";
  filter_data_arr(data_arr);
  if(!(pure_ram||pure_cam||g_ip->fully_assoc))
  {
    filter_tag_arr(t_min, tag_arr);
  }
  //cout << data_arr.size() << "\t" << tag_arr.size() <<" after\n";


  if (pure_ram||pure_cam||g_ip->fully_assoc)
  {
    for (miter = data_arr.begin(); miter != data_arr.end(); miter++)
    {
      uca_org_t & curr_org  = sol_list.back();
     // curr_org.tag_array2  = NULL;
      curr_org.data_array2 = *(*miter);

      curr_org.find_delay();
      curr_org.find_energy();
      curr_org.find_area();
      curr_org.find_cyc();

      //update min values for the entire cache
      cache_min.update_min_values(curr_org);

      sol_list.push_back(uca_org_t());
    }
  }
  else
  {
    while (tag_arr.empty() != true) 
    {
      mem_array * arr_temp = (tag_arr.back());
      //delete tag_arr.back();
      tag_arr.pop_back();

      for (miter = data_arr.begin(); miter != data_arr.end(); miter++)
      {
        uca_org_t & curr_org  = sol_list.back();
        curr_org.tag_array2  = *arr_temp;
        curr_org.data_array2 = *(*miter);

        curr_org.find_delay();
        curr_org.find_energy();
        curr_org.find_area();
        curr_org.find_cyc();

        //update min values for the entire cache
        cache_min.update_min_values(curr_org);

        sol_list.push_back(uca_org_t());
      }
    }
  }

  sol_list.pop_back();

  find_optimal_uca(fin_res, cache_min, sol_list);

  sol_list.clear();
/*
  for (miter = data_arr.begin(); miter != data_arr.end(); ++miter)
  {
    if (*miter != fin_res->data_array2)
    {
      delete *miter;
    }
  }
*/
  data_arr.clear();

  for (uint32_t t = 0; t < nthreads; t++)
  {
    delete calc_array[t].data_res;
    delete calc_array[t].tag_res;
  }

  delete [] calc_array;
//  delete cache_min;
//  delete d_min;
// delete t_min;
}

void update_dvs(uca_org_t *fin_res)
{
//	double dvs_voltage = g_ip->dvs_start; //initial voltage
//	double dvs_volt_step = 0.1; //Voltage should be raised in steps of 0.1V
//	int num_dvs_voltages = (g_ip->dvs_end - g_ip->dvs_start)/dvs_volt_step + 1;

	int pure_ram = (!g_ip->is_cache || g_ip->is_main_mem);
//	if(fin_res->tag_array2 || fin_res->data_array2)
	if(1)
	{
		Wire winit;//init before changing dvs
//		for (unsigned int i=0; i< num_dvs_voltages; i++) //For voltages from 0.2V-0.8V in steps of 0.1 . Total 7 voltages
		for (unsigned int i=0; i< g_ip->dvs_voltage.size(); i++)
		{
			fin_res->uca_q.push_back(new uca_org_t());

			g_ip->vdd = g_ip->dvs_voltage[i];
            if (g_ip->use_device_xml) {
              select_xml_vdd(g_ip);
              g_ip->load_sram_cell_xml();
            }
//			cout << "dvs : " << g_ip->dvs_voltage[i] << endl;
			init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um ,true);
			winit.wire_dvs_update();//Wire::wire_dvs_update();//Wire winit (1,1, false);

//			if(fin_res->tag_array2)
			if(1)
			{
				DynamicParameter tag_arr_dyn_p(true, g_ip->pure_ram, g_ip->pure_cam, fin_res->tag_array2.Nspd, fin_res->tag_array2.Ndwl, fin_res->tag_array2.Ndbl, fin_res->tag_array2.deg_bl_muxing, fin_res->tag_array2.Ndsam_lev_1, fin_res->tag_array2.Ndsam_lev_2, g_ip->is_main_mem);
				if(tag_arr_dyn_p.is_valid)
				{
					UCA * tag_arr = new UCA(tag_arr_dyn_p);
					//fin_res->uca_q[i]->tag_array2 = new mem_array();

					collect_uca_results(fin_res->tag_array2.Nspd, fin_res->tag_array2.Ndwl, fin_res->tag_array2.Ndbl, fin_res->tag_array2.deg_bl_muxing, fin_res->tag_array2.Ndsam_lev_1, fin_res->tag_array2.Ndsam_lev_2, tag_arr, &fin_res->uca_q[i]->tag_array2, g_ip->is_main_mem);
					delete tag_arr;
				}

			}
			DynamicParameter data_arr_dyn_p(false, g_ip->pure_ram, g_ip->pure_cam, fin_res->data_array2.Nspd, fin_res->data_array2.Ndwl, fin_res->data_array2.Ndbl, fin_res->data_array2.deg_bl_muxing, fin_res->data_array2.Ndsam_lev_1, fin_res->data_array2.Ndsam_lev_2, g_ip->is_main_mem);
			if(data_arr_dyn_p.is_valid)
			{
				UCA * data_arr = new UCA(data_arr_dyn_p);
				//fin_res->uca_q[i]->data_array2 = new mem_array();
				collect_uca_results(fin_res->data_array2.Nspd, fin_res->data_array2.Ndwl, fin_res->data_array2.Ndbl, fin_res->data_array2.deg_bl_muxing, fin_res->data_array2.Ndsam_lev_1, fin_res->data_array2.Ndsam_lev_2, data_arr, &fin_res->uca_q[i]->data_array2, g_ip->is_main_mem);
				delete data_arr;
			}

			fin_res->uca_q[i]->find_delay();
			fin_res->uca_q[i]->find_energy();
			fin_res->uca_q[i]->find_area();
			fin_res->uca_q[i]->find_cyc();

//            output_UCA(fin_res->uca_q[i]);
//            Wire::print_wire();

//			dvs_voltage = dvs_voltage + dvs_volt_step;
		}
		//reset input to original values in *.cfg file

		init_tech_params(g_ip->F_sz_um, g_ip->wire_F_sz_um, true);
	}
	else
	{
		cout << "ERROR: Cannot retrieve array structure for tag and data array" << endl;
		exit(1);
	}
}

