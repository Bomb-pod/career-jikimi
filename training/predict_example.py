# -*- coding: utf-8 -*-
"""
학습된 모델 사용 예시 — FastAPI 검증 엔드포인트에 넣을 코드의 원형.
사용법: python predict_example.py --model-dir train_out/final_model
"""
import argparse, json
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification


class ContextChecker:
    def __init__(self, model_dir, device=None):
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.tok = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir).to(self.device).eval()
        with open(f'{model_dir}/threshold.json', encoding='utf-8') as f:
            self.threshold = json.load(f)['threshold']

    @torch.no_grad()
    def check(self, history_msgs, candidate):
        """history_msgs: ['화자: 내용', ...] 최근 N개 / candidate: 보내려는 메시지
        returns: (verdict, confidence)  — 판정 로그 테이블의 verdict/confidence와 대응"""
        history = '\n'.join(history_msgs)
        enc = self.tok(history, candidate, truncation=True, max_length=512,
                       return_tensors='pt').to(self.device)
        prob = torch.softmax(self.model(**enc).logits.float(), -1)[0, 1].item()
        return ('부적절' if prob >= self.threshold else '적절'), round(prob, 4)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--model-dir', default='train_out/final_model')
    args = ap.parse_args()
    ck = ContextChecker(args.model_dir)
    demo = [
        (['팀장: 내일 배포 일정 확인해주세요.', '나: 네, 오전 중으로 정리하겠습니다.',
          '팀장: 롤백 계획도 포함해주세요.'],
         '넵, 롤백 절차까지 포함해서 문서로 공유드리겠습니다.'),
        (['팀장: 내일 배포 일정 확인해주세요.', '나: 네, 오전 중으로 정리하겠습니다.',
          '팀장: 롤백 계획도 포함해주세요.'],
         '오늘 저녁 치킨 ㄱ? 양념 반 후라이드 반 어때 ㅋㅋ'),
    ]
    for h, c in demo:
        v, p = ck.check(h, c)
        print(f'[{v} p={p}] {c}')
